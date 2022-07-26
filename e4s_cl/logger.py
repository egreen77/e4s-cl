"""E4S Container Launcher logging.

E4S CL has two channels for communicating with the user:
    1) sys.stdout via :any:`print`.
       Use this for messages the user has requested, e.g. a project listing.
    2) sys.stdout and sys.stderr via :any:`e4s_cl.logger`.
       Use this for status messages generated by E4S CL.

E4S CL also logs all status messages at the highest reporting level to
a rotating debug file in the user's E4S CL directory, typically "~/.local/e4s_cl".
"""

import os
import re
import sys
import time
import textwrap
import socket
import platform
import string
import logging
import hashlib
from pathlib import Path
from time import time
from logging import handlers
from datetime import datetime
from e4s_cl import USER_PREFIX, E4S_CL_VERSION
from e4s_cl.variables import is_parent
from e4s_cl.config import CONFIGURATION

try:
    import termcolor
    COLOR_OUTPUT = True
except ModuleNotFoundError:
    COLOR_OUTPUT = False

# Use isatty to check if the stream supports color
STDOUT_COLOR = os.isatty(sys.stdout.fileno())
STDERR_COLOR = os.isatty(sys.stderr.fileno())

# This is used all over the project, so name translation here
get_logger = logging.getLogger

WARNING = logging.WARNING
ERROR = logging.ERROR


def _prune_ansi(line: str) -> str:
    """
    Remove ANSI color codes from a string
    """
    return re.sub(re.compile('\x1b[^m]+m'), '', line)


def get_terminal_size():
    """Discover the size of the user's terminal.
    
    Several methods are attempted depending on the user's OS.
    If no method succeeds then default to (80, 25).
    
    Returns:
        tuple: (width, height) tuple giving the dimensions of the user's terminal window in characters.
    """
    default_width = 80
    default_height = 25
    dims = _get_term_size_env()

    if not dims:
        dims = _get_term_size_posix()

        if not dims:
            dims = default_width, default_height

    try:
        dims = list(map(int, dims))
    except ValueError:
        dims = default_width, default_height

    width = dims[0] if dims[0] >= 10 else default_width
    height = dims[1] if dims[1] >= 1 else default_height

    return width, height


def _get_term_size_tput():
    """Discover the size of the user's terminal via `tput`_.
    
    Returns:
        tuple: (width, height) tuple giving the dimensions of the user's terminal window in characters,
               or None if the size could not be determined.
               
    .. _tput: http://stackoverflow.com/questions/263890/how-do-i-find-the-width-height-of-a-terminal-window
    """
    try:
        import subprocess
        with subprocess.Popen(["tput", "cols"],
                              stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE) as proc:
            output = proc.communicate(input=None)
        cols = int(output[0])
        with subprocess.Popen(["tput", "lines"],
                              stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE) as proc:
            output = proc.communicate(input=None)
        rows = int(output[0])
        return (cols, rows)
    except:  # pylint: disable=bare-except
        return None


def _get_term_size_posix():
    """Discover the size of the user's terminal on a POSIX operating system (e.g. Linux).
    
    Returns:
        tuple: (width, height) tuple giving the dimensions of the user's terminal window in characters,
               or None if the size could not be determined.
    """

    # This function follows a POSIX naming scheme, not Python's.
    # pylint: disable=invalid-name
    # Sometimes Pylint thinks termios doesn't exist or doesn't have certain members even when it does.
    # pylint: disable=no-member
    def ioctl_GWINSZ(fd):
        try:
            import fcntl
            import termios
            import struct
            dims = struct.unpack('hh',
                                 fcntl.ioctl(fd, termios.TIOCGWINSZ, '1234'))
        except:  # pylint: disable=bare-except
            return None
        return dims

    dims = ioctl_GWINSZ(0) or ioctl_GWINSZ(1) or ioctl_GWINSZ(2)
    if not dims:
        try:
            fd = os.open(os.ctermid(), os.O_RDONLY)
            dims = ioctl_GWINSZ(fd)
            os.close(fd)
        except:  # pylint: disable=bare-except
            pass
    if not dims:
        return None
    return int(dims[1]), int(dims[0])


def _get_term_size_env():
    """Discover the size of the user's terminal via environment variables.
    
    The user may set the LINES and COLUMNS environment variables to control E4S CL's
    console dimension calculations.
    
    Returns:
        tuple: (width, height) tuple giving the dimensions of the user's terminal window in characters,
               or None if the size could not be determined.
    """
    try:
        return (int(os.environ['COLUMNS']), int(os.environ['LINES']))
    except (KeyError, ValueError):
        return None


def on_stdout(function):

    def wrapper(obj, record):
        text = function(obj, record)
        if STDOUT_COLOR:
            return text
        return _prune_ansi(text)

    return wrapper


def on_stderr(function):

    def wrapper(obj, record):
        text = function(obj, record)
        if STDERR_COLOR:
            return text
        return _prune_ansi(text)

    return wrapper


class LogFormatter(logging.Formatter):
    """Custom log message formatter.
    
    Controls message formatting for all levels.
    
    Args:
        line_width (int): Maximum length of a message line before line is wrapped.
        printable_only (bool): If True, never send unprintable characters to :any:`sys.stdout`.
    """
    # Allow invalid function names to define member functions named after logging levels.
    # pylint: disable=invalid-name

    _printable_chars = set(string.printable)

    def __init__(self, line_width=0, printable_only=False, allow_colors=True):
        super().__init__()
        self.printable_only = printable_only
        self.allow_colors = allow_colors
        self.line_width = line_width

    @on_stderr
    def CRITICAL(self, record):
        return self._colored(self._format_message(record), 'red', None,
                             ['bold'])

    @on_stderr
    def ERROR(self, record):
        return self._colored(self._format_message(record), 'red', None,
                             ['bold'])

    @on_stderr
    def WARNING(self, record):
        return self._colored(self._format_message(record), 'yellow', None,
                             ['bold'])

    @on_stdout
    def INFO(self, record):
        return self._format_message(record)

    @on_stderr
    def DEBUG(self, record):
        """
        Print a debug message with a neat little header
        """
        message = record.getMessage()
        if self.printable_only and (not set(message).issubset(
                self._printable_chars)):
            message = "<<UNPRINTABLE>>"

        if __debug__:
            marker = self._colored(
                f"[{record.levelname.title()} {record.name}:{record.lineno}]",
                'yellow')
        else:
            marker = self._colored(
                f"[{record.levelname.title()} {getattr(record, 'host', 'localhost')}:{record.process}]",
                'cyan', None, ['bold'])

        return f"{marker} {message}"

    def format(self, record):
        """Formats a log record.
        
        Args:
            record (LogRecord): LogRecord instance to format.
        
        Returns:
            str: The formatted record message.
            
        Raises:
            RuntimeError: No format specified for a the record's logging level.
        """
        try:
            return getattr(self, record.levelname)(record)
        except AttributeError as exc:
            raise RuntimeError(
                f"Unknown record level (name: {record.levelname})") from exc

    def _colored(self, text, *color_args):
        """Insert ANSII color formatting via `termcolor`_.
        
        Text colors:
            * grey
            * red
            * green
            * yellow
            * blue
            * magenta
            * cyan
            * white
        
        Text highlights:
            * on_grey
            * on_red
            * on_green
            * on_yellow
            * on_blue
            * on_magenta
            * on_cyan
            * on_white

        Attributes:
            * bold
            * dark
            * underline
            * blink
            * reverse
            * concealed
        
        .. _termcolor: http://pypi.python.org/pypi/termcolor
        """
        if COLOR_OUTPUT and self.allow_colors and color_args:
            return termcolor.colored(text, *color_args)
        return text

    def _format_message(self, record, header=''):
        # Length of the header, pruned from invisible escape characters
        if self.line_width:
            header_length = len(_prune_ansi(header))

            output = []
            text = record.getMessage().split("\n")

            # Strip empty lines at the end only
            while len(text) > 1 and not text[-1]:
                text.pop()

            for line in text:
                output += textwrap.wrap(line,
                                        width=(self.line_width -
                                               header_length))
                if not line:
                    output += ['']

            return textwrap.indent("\n".join(output), header,
                                   lambda line: True)
        return textwrap.indent(record.getMessage().strip(), header,
                               lambda line: True)


def set_log_level(level):
    """Sets :any:`LOG_LEVEL`, the output level for stdout logging objects.
    
    Changes to LOG_LEVEL may affect software package verbosity. 
    
    Args:
        level (str): A string identifying the logging level, e.g. "INFO".
    """
    # Use of global statement is justified in this case.
    # pylint: disable=global-statement
    global LOG_LEVEL
    LOG_LEVEL = level.upper()
    _STDERR_HANDLER.setLevel(LOG_LEVEL)


def debug_mode():
    return LOG_LEVEL == 'DEBUG'


LOG_LEVEL = 'INFO'
"""str: The global logging level for stdout loggers and software packages.

Don't change directly. May be changed via :any:`set_log_level`.  
"""

LOG_FILE = Path(USER_PREFIX, 'logs', 'debug_log')
"""str: Absolute path to a log file to receive all debugging output."""

LOG_INDEX = Path(USER_PREFIX, 'logs', 'index.tsv')
"""str: Absolute path to a log file to receive all debugging output."""

LOG_LATEST = Path(USER_PREFIX, 'logs', 'latest')

TERM_SIZE = get_terminal_size()
"""tuple: (width, height) tuple of detected terminal dimensions in characters."""

LINE_WIDTH = TERM_SIZE[0]
"""Width of a line on the terminal.

Uses system specific methods to determine console line width.  If the line
width cannot be determined, the default is 80.
"""

LOG_ID_MARKER = "__E4S_CL_LOG_ID"
"""
Environment variable name: set by the parent for every execution, is used to
group debug logs in folders
"""


def setup_process_logger(name: str) -> logging.Logger:
    """
    Create and setup handlers of a Logger object meant to log errors of
    a subprocess
    """

    # Locate and ensure the log file directory is writeable
    # - Compatible with symlinks in LOG_ID
    log_file = Path(_LOG_FILE_PREFIX, LOG_ID, name).resolve()
    Path.mkdir(log_file.parent, parents=True, exist_ok=True)

    # Create a logger in debug mode
    process_logger = logging.getLogger(name)
    if CONFIGURATION.disable_ranked_log:
        process_logger.setLevel(logging.ERROR)
        process_logger.propagate = False
    else:
        process_logger.setLevel(logging.DEBUG)

        # Log process data to file
        handler = logging.FileHandler(log_file,
                                      mode='a',
                                      encoding='utf-8',
                                      delay=True)
        handler.setFormatter(LogFormatter(line_width=120, allow_colors=False))
        process_logger.addHandler(handler)

        # This disables the propagation along the logger tree, to avoid getting
        # everything on stderr
        process_logger.propagate = False

    return process_logger


def is_available(file: Path) -> bool:
    """
    Returns True if the path passed as an argument is accessible to write
    The parents of the passed file will be create if not existent
    """
    parent_dir = file.parent

    if parent_dir.is_symlink():
        parent_dir = parent_dir.resolve()

    try:
        # Ensure the file directory is accessible, create it if need be
        Path.mkdir(parent_dir, parents=True, exist_ok=True)

        with open(file, 'a', encoding='utf-8') as _:
            pass
    except OSError as exc:
        _ROOT_LOGGER.debug("Failed to open file %s: %s", file.as_posix(),
                           exc.strerror)
        return False
    return True


def add_file_handler(
    log_file: Path,
    logger: logging.Logger,
    formatter: logging.Formatter = LogFormatter(line_width=120,
                                                allow_colors=False)
) -> bool:
    """
    Add a file handler to a Logger object
    """
    if not is_available(log_file):
        return False

    file_handler = handlers.TimedRotatingFileHandler(log_file,
                                                     when='D',
                                                     interval=1,
                                                     backupCount=3)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    return True


_ROOT_LOGGER = logging.getLogger()
if not _ROOT_LOGGER.handlers:
    _ROOT_LOGGER.setLevel(logging.DEBUG)
    _LOG_FILE_PREFIX = LOG_FILE.parent

    # Setup output on stderr
    _STDERR_HANDLER = logging.StreamHandler(sys.stderr)
    _STDERR_HANDLER.setFormatter(LogFormatter(printable_only=False))
    _STDERR_HANDLER.setLevel(LOG_LEVEL)

    _ROOT_LOGGER.addHandler(_STDERR_HANDLER)

# Create a hash for the execution ID, and dictate to dump logs in the
# corresponding folder
if is_parent():
    grinder = hashlib.sha256()
    grinder.update(str(time()).encode())

    LOG_ID = grinder.hexdigest()
    os.environ[LOG_ID_MARKER] = LOG_ID
else:
    LOG_ID = os.environ.get(LOG_ID_MARKER)

if is_parent():
    # Add a file handler, location depending on the status of the process
    add_file_handler(LOG_FILE, _ROOT_LOGGER)

    # When running as e4s-cl
    if Path(sys.argv[0]).name == 'e4s-cl':
        # Log the command in a database to ease human lookup
        index_logger = logging.getLogger("index")
        index_logger.propagate = False
        add_file_handler(LOG_INDEX,
                         index_logger,
                         formatter=logging.Formatter(
                             fmt=f"%(asctime)s\t{LOG_ID}\t%(message)s"))
        index_logger.info(" ".join(sys.argv))

        # Create a symlink towards the latest log directory
        try:
            os.unlink(LOG_LATEST)
        except OSError as err:
            _ROOT_LOGGER.debug("Unlink %s failed: %s", LOG_LATEST.as_posix(),
                               str(err))

        try:
            os.symlink(Path(LOG_FILE.parent, LOG_ID), LOG_LATEST)
        except OSError as err:
            _ROOT_LOGGER.debug("Symlink %s failed: %s", LOG_LATEST.as_posix(),
                               str(err))
        else:
            os.environ[LOG_ID_MARKER] = LOG_LATEST.name

    # pylint: disable=logging-not-lazy
    _ROOT_LOGGER.debug(
        ("\n%(bar)s\n"
         "E4S CONTAINER LAUNCHER LOGGING INITIALIZED\n"
         "\n"
         "Timestamp         : %(timestamp)s\n"
         "Hostname          : %(hostname)s\n"
         "Platform          : %(platform)s\n"
         "Version           : %(version)s\n"
         "Python Version    : %(pyversion)s\n"
         "Working Directory : %(cwd)s\n"
         "Terminal Size     : %(termsize)s\n"
         "Frozen            : %(frozen)s\n"
         "Log ID            : %(logid)s\n"
         "%(bar)s\n") % {
             'bar': '#' * LINE_WIDTH,
             'timestamp': str(datetime.now()),
             'hostname': socket.gethostname(),
             'platform': platform.platform(),
             'version': E4S_CL_VERSION,
             'pyversion': platform.python_version(),
             'cwd': os.getcwd(),
             'termsize': 'x'.join([str(_) for _ in TERM_SIZE]),
             'frozen': getattr(sys, 'frozen', False),
             'logid': LOG_ID,
         })
elif not CONFIGURATION.disable_ranked_log:
    _log_file = Path(_LOG_FILE_PREFIX, LOG_ID, f"e4s_cl.{os.getpid()}")
    add_file_handler(_log_file, _ROOT_LOGGER)
