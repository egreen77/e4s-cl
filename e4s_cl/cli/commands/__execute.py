"""Execute command

Definition of arguments and hooks related to the execute command,
file import calculations, and execution of a program passed as an
argument.
This command is used internally and thus cloaked from the UI
"""

from pathlib import Path
from sotools.libraryset import LibrarySet, Library
from e4s_cl import (EXIT_SUCCESS, E4S_CL_SCRIPT, logger, variables)
from e4s_cl.error import InternalError
from e4s_cl.cli import arguments
from e4s_cl.cli.command import AbstractCommand
from e4s_cl.cf.template import Entrypoint
from e4s_cl.cf.containers import Container, BackendError, FileOptions
from e4s_cl.cf.libraries import (libc_version, library_links)
from e4s_cl.cf.wi4mpi import (wi4mpi_enabled, wi4mpi_root, wi4mpi_import,
                              wi4mpi_libraries, wi4mpi_libpath, wi4mpi_preload)

LOGGER = logger.get_logger(__name__)
_SCRIPT_CMD = Path(E4S_CL_SCRIPT).name


def import_library(shared_object, container):
    """
    This method binds the shared object it got as an argument, along with all
    the symbolic links that may exist and point to the same file.

    This is because depending on the linker at compile-time some binaries
    require more or less precise versions of the same file (eg. libmpi.so for
    some and libmpi.so.12 for others). Binding all the references ensures the
    library is found down the line.
    """
    for file in library_links(shared_object):
        container.bind_file(file, Path(container.import_library_dir,
                                       file.name))


# pylint: disable=unused-argument
def filter_libraries(library_set, container, entrypoint):
    """ Library filter

    library_paths: list[pathlib.Path]
    container: e4s_cl.cf.containers.Container

    This method filters out libraries that may cause problems when imported
    in a newer glibc environment
    """

    filtered_set = LibrarySet(library_set)

    # Remove libc-tied libraries from the filtered set, including the linker
    for lib in library_set.glib:
        filtered_set.remove(lib)

    return filtered_set


def overlay_libraries(library_set, container, entrypoint):
    """ Library overlay

    library_paths: list[pathlib.Path]
    container: e4s_cl.cf.containers.Container

    This method selects all the libraries defined in the list, along with
    with the host's (implicitly newer) linker.
    """
    selected = library_set

    # Figure out what to if multiple linkers are required
    if len(library_set.linkers) != 1:
        raise InternalError(
            f"{len(library_set.linkers)} linkers detected. This should not happen."
        )

    for linker in library_set.linkers:
        entrypoint.linker = Path(container.import_library_dir,
                                 Path(linker.binary_path).name).as_posix()
        container.bind_file(linker.binary_path,
                            dest=Path(container.import_library_dir,
                                      Path(linker.binary_path).name))

    return selected


def select_libraries(library_set, container, entrypoint):
    """ Select the libraries to make available in the future container

    library_paths: list[pathlib.Path]

    This method checks the libc versions compatibilities and returns a
    list of libraries safe to bind dependending on that check.

    If the container's linker is more recent than the hosts, it must be used.
    libc.so's version must equals the linker's. Some libraries must be bound,
    some must not as they exist in the container, tied to its linker.
     => filter_libraries

    However, if the host linker is newer, the host libc is newer, and libraries
    fail if used with the older libc of the container. We must then bind it,
    but binding libc implies binding the linker too, as both need to match.
    In the process, we bind all the necessary libraries.
     => overlay_libraries

    Why not overlay in both cases you ask ? As we run container-compiled
    binaries, they expect a minimal version of libc. It is fine to run with
    a newer libc, but very hazardous to run with an older one.
    """

    host_newer = True
    guest_newer = False

    host_libc = libc_version()
    guest_libc = container.libc_v

    methods = {host_newer: overlay_libraries, guest_newer: filter_libraries}

    host_precedence = host_libc > guest_libc

    LOGGER.debug("Host libc: %s %s Guest libc: %s", str(host_libc),
                 '>' if host_precedence else '<=', str(guest_libc))

    return methods[host_precedence](library_set, container, entrypoint)


class ExecuteCommand(AbstractCommand):
    """``execute`` subcommand."""

    def _construct_parser(self):
        usage = f"{self.command} [arguments] <command> [command_arguments]"
        parser = arguments.get_parser(prog=self.command,
                                      usage=usage,
                                      description=self.summary)
        parser.add_argument("--backend",
                            type=str,
                            dest='backend',
                            required=True,
                            help="Specify the backend name",
                            metavar='backend')

        parser.add_argument('--image',
                            type=str,
                            dest='image',
                            required=True,
                            help="Container image to use",
                            metavar='image')

        parser.add_argument('--files',
                            type=arguments.existing_posix_path_list,
                            help="Files to bind, comma-separated",
                            metavar='files')

        parser.add_argument('--libraries',
                            type=arguments.existing_posix_path_list,
                            help="Libraries to bind, comma-separated",
                            default=[],
                            metavar='libraries')

        parser.add_argument('--source',
                            type=arguments.existing_posix_path,
                            help="Script to source",
                            metavar='libraries')

        parser.add_argument('cmd',
                            type=str,
                            help="Executable command, e.g. './a.out'",
                            metavar='command',
                            nargs=arguments.REMAINDER)

        return parser

    def main(self, argv):
        args = self._parse_args(argv)

        try:
            container = Container(name=args.backend, image=args.image)
        except BackendError as err:
            return err.handle(type(err), err, None)

        # Setup a entrypoint object that will later be bound as a bash script
        params = Entrypoint()

        # Bind files to make the sourced script accessible
        if args.files:
            for path in args.files:
                container.bind_file(path, option=FileOptions.READ_WRITE)

        # This script is sourced before any other command in the container
        params.source_script_path = args.source

        # If WI4MPI is enabled, analyze the libraries it uses
        required_libraries = args.libraries + wi4mpi_libraries(wi4mpi_root())

        # The following is a set of all libraries required. It
        # is used in the container to check version mismatches
        libset = LibrarySet.create_from(required_libraries)
        if libset:
            # Analyze the container to get library information from the environment
            # it offers, using the entrypoint and the above libraries
            container.get_data()

        # Setup the final command and metadata relating to the execution
        params.command = args.cmd
        params.debug = logger.debug_mode()
        params.library_dir = container.import_library_dir.as_posix()

        if wi4mpi_enabled():
            linker_paths = map(lambda x: x.as_posix(),
                               wi4mpi_libpath(wi4mpi_root()))
            params.library_dir = ':'.join(
                [*linker_paths,
                 container.import_library_dir.as_posix()])

        if wi4mpi_enabled():
            # Import relevant files
            wi4mpi_import(container, wi4mpi_root())

            params.preload += wi4mpi_preload(wi4mpi_root())

        if libset:
            # Create a set of libraries to import
            libset = select_libraries(libset, container, params)

            for line in libset.ldd_format():
                LOGGER.debug(line)

            # Import each library along with all symlinks pointing to it
            for shared_object in libset:
                import_library(shared_object, container)

            if not wi4mpi_enabled():
                # Preload the roots of all the set's trees
                def _path(library: Library):
                    return Path(container.import_library_dir,
                                Path(library.binary_path).name).as_posix()

                for import_path in map(_path, libset.top_level):
                    params.preload.append(import_path)

        # Write the entry script to a file, then bind it to the container
        script_name = params.setup()
        container.bind_file(script_name, dest=container.script)

        command = [container.script]

        if variables.is_dry_run():
            LOGGER.info("Running %s in container %s", command, container)
            params.teardown()
            return EXIT_SUCCESS

        code = container.run(command)

        if code:
            LOGGER.critical("Container command failed with error code %d",
                            code)

        params.teardown()

        return code


COMMAND = ExecuteCommand(
    __name__,
    summary_fmt=
    "Execute a command in a container with a tailor-made environment.")