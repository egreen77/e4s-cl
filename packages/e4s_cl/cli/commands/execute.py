import os
from pathlib import Path
from e4s_cl import EXIT_SUCCESS, HELP_CONTACT, E4S_CL_SCRIPT
from e4s_cl import logger, cli
from e4s_cl.util import list_dependencies
from e4s_cl.cli import arguments
from e4s_cl.cli.command import AbstractCommand
from argparse import ArgumentTypeError
from e4s_cl.cf import containers

LOGGER = logger.get_logger(__name__)
_SCRIPT_CMD = os.path.basename(E4S_CL_SCRIPT)

def _path_comma_list(string):
    items = [Path(data) for data in string.split(',')]

    for path in items:
        if not path.exists():
            raise ArgumentTypeError("File {} does not exist".format(path.as_posix()))

    return items

def compute_libs(lib_list, container):
    output = container.run(['ldconfig', '-p'], redirect_stdout=True)
    present_in_container = [line.strip().split(' ')[0] for line in output[1:]]
    selected = {}

    for path in lib_list:
        dependencies = list_dependencies(path)
        for dependency in dependencies.keys():
            if dependency not in present_in_container and dependencies[dependency]['path']:
                selected.update({dependency: dependencies[dependency]['path']})

    for path in selected.values():
        container.bind_file(path, dest="/hostlibs{}".format(path), options='ro')

class ExecuteCommand(AbstractCommand):
    """``help`` subcommand."""

    @classmethod
    def _parse_dependencies(cls, libraries):
        deps = {}

        for path in libraries:
            deps.update(list_dependencies(path))

        return deps

    def _construct_parser(self):
        usage = "%s [arguments] <command> [command_arguments]" % self.command
        parser = arguments.get_parser(prog=self.command, usage=usage, description=self.summary)
        parser.add_argument('--image',
                            help="Container image to use",
                            #type= TODO Container iamge checking method
                            metavar='image')
        parser.add_argument('--files',
                            help="Files to bind, comma-separated",
                            metavar='files',
                            type=_path_comma_list)
        parser.add_argument('--libraries',
                            help="Libraries to bind, comma-separated",
                            metavar='libraries',
                            type=_path_comma_list)
        parser.add_argument('cmd',
                            help="Executable command, e.g. './a.out'",
                            metavar='command',
                            type=str,
                            nargs=arguments.REMAINDER)

        if containers.BACKENDS:
            group = parser.add_mutually_exclusive_group(required=True)
            for backend in containers.BACKENDS:
                group.add_argument("--{}".format(backend),
                        help="Use {} as the container backend".format(backend),
                        dest='backend',
                        action='store_const',
                        const=backend)

        return parser

    def main(self, argv):
        args = self._parse_args(argv)
        container = containers.Container(backend=args.backend, image=args.image)

        if args.libraries:
            compute_libs(args.libraries, container)
            container.bind_env_var('LD_LIBRARY_PATH', '/hostlibs')

        if args.files:
            for path in args.files:
                container.bind_file(path, dest=path, options='ro')

        container.run(args.cmd, redirect_stdout=False)

        return EXIT_SUCCESS
    
COMMAND = ExecuteCommand(__name__, summary_fmt="Execute a command in a container with a tailor-made environment.")
