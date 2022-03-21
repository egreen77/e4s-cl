"""Utility functions.

Handles system manipulation and status tasks, e.g. subprocess management or file creation.
"""

import os
import re
import sys
import subprocess
import pkgutil
from pathlib import Path
import hashlib
import json
from functools import lru_cache
from shutil import which as sh_which
from collections import deque
from time import perf_counter
from contextlib import contextmanager
from e4s_cl import logger
from e4s_cl.variables import ParentStatus
from e4s_cl.error import InternalError

try:
    import termcolor
    COLOR_OUTPUT = True
except ModuleNotFoundError:
    COLOR_OUTPUT = False

LOGGER = logger.get_logger(__name__)

# Suppress debugging messages in optimized code
if __debug__:
    _heavy_debug = LOGGER.debug  # pylint: disable=invalid-name
else:

    def _heavy_debug(*args, **kwargs):
        # pylint: disable=unused-argument
        pass


_PY_SUFFEXES = ('.py', '.pyo', '.pyc')

# Don't make this a raw string!  \033 is unicode for '\x1b'.
_COLOR_CONTROL_RE = re.compile('\033\\[([0-9]|3[0-8]|4[0-8])m')


def mkdirp(path: Path) -> bool:
    """Creates a directory and all its parents.
    
    Works just like ``mkdir -p``.
    
    Args:
        path: Path to create.
    """

    if not isinstance(path, Path):
        path = Path(path)

    try:
        path.mkdir(parents=True, exist_ok=True)
    except PermissionError as err:
        LOGGER.error("Failed to create directory %s: %s", path.as_posix(),
                     str(err))
        return False
    except FileExistsError as err:
        LOGGER.error("File %s exists and is not a directory: %s",
                     path.as_posix(), str(err))

    return True


@lru_cache()
def which(*args, **kwargs):
    return sh_which(*args, **kwargs)


def path_accessible(path: Path, mode: str = 'r') -> bool:
    """Check if a file or directory exists and is accessible.
    
    Files are checked by attempting to open them with the given mode.
    Directories are checked by testing their access bits only, which may fail for 
    some filesystems which may have permissions semantics beyond the usual POSIX 
    permission-bit model. We'll fix this if it becomes a problem. 
    
    Args:
        path (str): Path to file or directory to check.
        mode (str): File access mode to test, e.g. 'r' or 'rw'
    
    Returns:
        True if the file exists and can be opened in the specified mode, False otherwise.
    """
    if isinstance(path, str):
        path = Path(path)

    modes = {'r': os.R_OK, 'w': os.W_OK, 'x': os.X_OK}

    if not mode:
        raise InternalError(f"Unsupported value for mode: '{mode}'")
    for element in mode:
        if element not in modes:
            raise InternalError(f"Unsupported value for mode: '{element}'")

    modebits = 0
    for char in mode:
        modebits |= modes[char]
    return os.access(path.as_posix(), os.F_OK) and os.access(
        path.as_posix(), modebits)


def run_subprocess(cmd, cwd=None, env=None) -> int:
    """
    cmd: list[str],
    env: Optional[dict]
    Run a subprocess, tailored for end subrocesses
    """
    subproc_env = os.environ
    if env:
        for key, val in env.items():
            if val is None:
                subproc_env.pop(key, None)
                _heavy_debug("unset %s", key)
            else:
                subproc_env[key] = val
                _heavy_debug("%s=%s", key, val)

    # Store the N last lines of error in a fast container
    buffer = deque(maxlen=100)

    with subprocess.Popen(cmd,
                          cwd=cwd,
                          env=subproc_env,
                          stdout=sys.stdout,
                          stderr=subprocess.PIPE,
                          close_fds=False,
                          universal_newlines=True,
                          bufsize=1) as proc:
        # Save the PID for later use
        pid = proc.pid
        # Setup a logger dedicated to this subprocess
        process_logger = logger.setup_process_logger(f"process.{pid}")
        with proc.stderr:
            # Log the errors in a log file
            for line in proc.stderr.readlines():
                process_logger.error(line[:-1])
                buffer.append(line)
        returncode = proc.wait()

    # In case of error, output information
    if returncode:
        LOGGER.error("Process %d failed with code %d:", pid, returncode)
        for line in buffer:
            LOGGER.error(line)
        log_file = getattr(process_logger.handlers[0], 'baseFilename', None)
        if log_file:
            LOGGER.error("See %s for details.", log_file)
    else:
        LOGGER.debug("Process %d returned %d", pid, returncode)

    del process_logger

    return returncode


def run_e4scl_subprocess(cmd, cwd=None, env=None, capture_output=False) -> int:
    """
    cmd: list[str],
    env: Optional[dict],
    capture_output: bool
    Run a subprocess, tailored for recursive e4s-cl processes
    """
    with ParentStatus():
        subproc_env = os.environ
        if env:
            for key, val in env.items():
                if val is None:
                    subproc_env.pop(key, None)
                    _heavy_debug("unset %s", key)
                else:
                    subproc_env[key] = val
                    _heavy_debug("%s=%s", key, val)

        with subprocess.Popen(
                cmd,
                cwd=cwd,
                env=subproc_env,
                stdout=subprocess.PIPE if capture_output else sys.stdout,
                stderr=sys.stderr,
                close_fds=False,
                universal_newlines=True,
                bufsize=1) as proc:

            returncode = proc.wait()
            if capture_output:
                output = proc.stdout.read()

    if capture_output:
        return returncode, output
    return returncode


def get_command_output(cmd):
    """Return the possibly cached output of a command.
    
    Just :any:`subprocess.check_output` with a cache.
    Subprocess stderr is always sent to subprocess stdout.
    
    Args:
        cmd (list): Command and its command line arguments.

    Raises:
        subprocess.CalledProcessError: return code was non-zero.
        
    Returns:
        str: Subprocess output.
    """
    key = repr(cmd)
    try:
        return get_command_output.cache[key]
    except AttributeError:
        get_command_output.cache = {}
    except KeyError:
        pass
    else:
        _heavy_debug("Using cached output for command: %s", cmd)
    LOGGER.debug("Checking subprocess output: %s", cmd)
    stdout = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    get_command_output.cache[key] = stdout
    _heavy_debug(stdout)
    LOGGER.debug("%s returned 0", cmd)
    return stdout


def page_output(output_string):
    """Pipe string to a pager.

    If PAGER is an environment then use that as pager, otherwise
    use `less`.

    Args:
        output_string (str): String to put output.

    """
    if os.environ.get('__E4S_CL_ENABLE_PAGER__', False):
        pager_cmd = os.environ.get('PAGER', 'less -F -R -S -X -K').split(' ')
        with subprocess.Popen(pager_cmd, stdin=subprocess.PIPE) as proc:
            proc.communicate(bytearray(output_string, 'utf-8'))
    else:
        print(output_string)


def parse_bool(value, additional_true=None, additional_false=None):
    """Parses a value to a boolean value.
    
    If `value` is a string try to interpret it as a bool:
    * ['1', 't', 'y', 'true', 'yes', 'on'] ==> True
    * ['0', 'f', 'n', 'false', 'no', 'off'] ==> False
    Otherwise raise TypeError.
    
    Args:
        value: value to parse to a boolean.
        additional_true (list): optional additional string values that stand for True.
        additional_false (list): optional additional string values that stand for False.
        
    Returns:
        bool: True if  `value` is true, False if `value` is false.
        
    Raises:
        ValueError: `value` does not parse.
    """
    true_values = ['1', 't', 'y', 'true', 'yes', 'on']
    false_values = ['0', 'f', 'n', 'false', 'no', 'off', 'none']
    if additional_true:
        true_values.extend(additional_true)
    if additional_false:
        false_values.extend(additional_false)
    if isinstance(value, str):
        value = value.lower()
        if value in true_values:
            return True
        if value in false_values:
            return False
        raise TypeError
    return bool(value)


def hline(title, *args, **kwargs):
    """Build a colorful horizontal rule for console output.
    
    Uses :any:`logger.LINE_WIDTH` to generate a string of '=' characters
    as wide as the terminal.  `title` is included in the string near the
    left of the horizontal line. 
    
    Args:
        title (str): Text to put on the horizontal rule.
        *args: Positional arguments to pass to :any:`termcolor.colored`.
        **kwargs: Keyword arguments to pass to :any:`termcolor.colored`.
    
    Returns:
        str: The horizontal rule.
    """
    text = f"== {title} ==".rjust(logger.LINE_WIDTH, '=')
    return color_text(text, *args, **kwargs)


def color_text(text, *args, **kwargs):
    """Use :any:`termcolor.colored` to colorize text.
    
    Args:
        text (str): Text to colorize.
        *args: Positional arguments to pass to :any:`termcolor.colored`.
        **kwargs: Keyword arguments to pass to :any:`termcolor.colored`.
        
    Returns:
        str: The colorized text.
    """
    if sys.stdout.isatty() and COLOR_OUTPUT:
        return termcolor.colored(text, *args, **kwargs)
    return text


def uncolor_text(text):
    """Remove color control chars from a string.
    
    Args:
        text (str): Text to colorize.
        
    Returns:
        str: The text without control chars.
    """
    return re.sub(_COLOR_CONTROL_RE, '', text)


def walk_packages(path, prefix):
    """Fix :any:`pkgutil.walk_packages` to work with Python zip files.

    Python's default :any:`zipimporter` doesn't provide an `iter_modules` method so
    :any:`pkgutil.walk_packages` silently fails to list modules and packages when
    they are in a zip file.  This implementation works around this.
    """

    def seen(path, dct={}):  # pylint: disable=dangerous-default-value
        if path in dct:
            return True
        dct[path] = True
        return False

    for importer, name, ispkg in _iter_modules(path, prefix):
        yield importer, name, ispkg
        if ispkg:
            __import__(name)
            path = getattr(sys.modules[name], '__path__', None) or []
            path = [p for p in path if not seen(p)]
            for item in walk_packages(path, name + '.'):
                yield item


def _iter_modules(paths, prefix):
    # pylint: disable=no-member
    yielded = {}
    for importer, name, ispkg in pkgutil.iter_modules(path=paths,
                                                      prefix=prefix):
        if name not in yielded:
            yielded[name] = True
            yield importer, name, ispkg


def flatten(nested_list):
    """Flatten a nested list."""
    return [item for sublist in nested_list for item in sublist]


def hash256(string):
    """
    Create a hash from a string
    """
    grinder = hashlib.sha256()
    grinder.update(string.encode())
    return grinder.hexdigest()


def _json_serializer(obj):
    """
    JSON add-on that will transform classes into dicts, and sets into special
    objects to be decoded back into sets with `util.JSONDecoder`.
    """
    if getattr(obj, '__dict__', False):
        return {'__type': type(obj).__name__, '__dict': obj.__dict__}
    if isinstance(obj, set):
        return {'__type': 'set', '__list': list(obj)}

    return obj


# Dict of methods to use when decoding e4s-cl json. Keys correspond to values
# of the `__type` field.
JSON_HOOKS = {}


def _json_decoder(obj):
    """
    JSON add-on to decode dicts with embedded data from `util.JSONSerializer`
    """
    if obj.get('__type', False):
        if obj['__type'] == 'set':
            return set(obj['__list'])

        if obj['__type'] in JSON_HOOKS:
            return JSON_HOOKS[obj['__type']](obj['__dict'])

    return obj


def json_dumps(*args, **kwargs):
    """
    json.dumps wrapper
    """
    if kwargs.get('default'):
        raise InternalError("Cannot override default from util.json_dumps")

    kwargs['default'] = _json_serializer

    return json.dumps(*args, **kwargs)


def json_loads(*args, **kwargs):
    """
    json.loads wrapper
    """
    if kwargs.get('object_hook'):
        raise InternalError("Cannot override object_hook from util.json_loads")

    kwargs['object_hook'] = _json_decoder

    return json.loads(*args, **kwargs)


def add_dot(string: str) -> str:
    if string[-1] in ['.', '!', '?']:
        return string
    return string + '.'


def update_ld_path(path: Path):
    ld_path = os.environ.get('LD_LIBRARY_PATH')

    if ld_path:
        ld_path = f"{path.as_posix()}{os.pathsep}{ld_path}"
    else:
        ld_path = path.as_posix()

    os.environ['LD_LIBRARY_PATH'] = ld_path
    return ld_path


@contextmanager
def catchtime() -> float:
    start = perf_counter()
    yield lambda: perf_counter() - start