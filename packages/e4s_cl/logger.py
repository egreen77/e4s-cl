# -*- coding: utf-8 -*-
#
# Copyright (c) 2015, ParaTools, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# (1) Redistributions of source code must retain the above copyright notice,
#     this list of conditions and the following disclaimer.
# (2) Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions and the following disclaimer in the documentation
#     and/or other materials provided with the distribution.
# (3) Neither the name of ParaTools, Inc. nor the names of its contributors may
#     be used to endorse or promote products derived from this software without
#     specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
"""E4S Container Launcher logging.

E4S CL has two channels for communicating with the user:
    1) sys.stdout via :any:`print`.
       Use this for messages the user has requested, e.g. a project listing.
    2) sys.stdout and sys.stderr via :any:`taucmdr.logger`.
       Use this for status messages generated by E4S CL.

E4S CL also logs all status messages at the highest reporting level to
a rotating debug file in the user's E4S CL directory, typically "~/.local/e4s_cl".
"""

import os
import re
import sys
import errno
import textwrap
import socket
import platform
import string
import logging
from logging import handlers
from datetime import datetime
import termcolor
from e4s_cl import USER_PREFIX, E4S_CL_VERSION, variables

IDENTIFIER = "e4s-cl-"


def slave_error(level, message):
    if isinstance(message, str):
        return "{}{} {} {} {}".format(IDENTIFIER, level, os.getpid(),
                                      socket.gethostname(), message.strip())


def _prune_ansi(line):
    pattern = re.compile('\x1b[^m]+m')
    match = pattern.search(line)
    while match:
        index = line.find(match.group(0))
        line = line[:index] + line[index + len(match.group(0)):]
        match = pattern.search(line)
    return line


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
        current_os = platform.system()
        if current_os == 'Windows':
            dims = _get_term_size_windows()
            if not dims:
                # for window's python in cygwin's xterm
                dims = _get_term_size_tput()
        if current_os == 'Linux' or current_os == 'Darwin' or current_os.startswith(
                'CYGWIN'):
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


def _get_term_size_windows():
    """Discover the size of the user's terminal on Microsoft Windows.
    
    Returns:
        tuple: (width, height) tuple giving the dimensions of the user's terminal window in characters,
               or None if the size could not be determined.
    """
    res = None
    try:
        from ctypes import windll, create_string_buffer
        # stdin handle is -10, stdout -11, stderr -12
        handle = windll.kernel32.GetStdHandle(-12)
        csbi = create_string_buffer(22)
        res = windll.kernel32.GetConsoleScreenBufferInfo(handle, csbi)
    except:  # pylint: disable=bare-except
        return None
    if res:
        import struct
        (_, _, _, _, _, left, top, right, bottom, _,
         _) = struct.unpack("hhhhHhhhhhh", csbi.raw)
        sizex = right - left + 1
        sizey = bottom - top + 1
        return sizex, sizey
    else:
        return None


def _get_term_size_tput():
    """Discover the size of the user's terminal via `tput`_.
    
    Returns:
        tuple: (width, height) tuple giving the dimensions of the user's terminal window in characters,
               or None if the size could not be determined.
               
    .. _tput: http://stackoverflow.com/questions/263890/how-do-i-find-the-width-height-of-a-terminal-window
    """
    try:
        import subprocess
        proc = subprocess.Popen(["tput", "cols"],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE)
        output = proc.communicate(input=None)
        cols = int(output[0])
        proc = subprocess.Popen(["tput", "lines"],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE)
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
        return (int(os.environ['LINES']), int(os.environ['COLUMNS']))
    except (KeyError, ValueError):
        return None


class LogFormatter(logging.Formatter, object):
    """Custom log message formatter.
    
    Controls message formatting for all levels.
    
    Args:
        line_width (int): Maximum length of a message line before line is wrapped.
        printable_only (bool): If True, never send unprintable characters to :any:`sys.stdout`.
    """
    # Allow invalid function names to define member functions named after logging levels.
    # pylint: disable=invalid-name

    _printable_chars = set(string.printable)

    def __init__(self, line_width, printable_only=False, allow_colors=True):
        super(LogFormatter, self).__init__()
        self.printable_only = printable_only
        self.allow_colors = allow_colors
        self.line_width = line_width
        self.line_marker = COLORED_LINE_MARKER if allow_colors else LINE_MARKER
        self._text_wrapper = textwrap.TextWrapper(
            width=self.line_width + len(self.line_marker),
            initial_indent=self.line_marker,
            subsequent_indent=self.line_marker + '    ',
            break_long_words=False,
            break_on_hyphens=False,
            drop_whitespace=False)

    def CRITICAL(self, record):
        return self._msgbox(record, 'X')

    def ERROR(self, record):
        if variables.STATUS == variables.MASTER:
            return self._msgbox(record, '!')
        return slave_error('error', record.msg)

    def WARNING(self, record):
        if variables.STATUS == variables.MASTER:
            return self._msgbox(record, '*')
        return slave_error('warning', record.msg)

    def INFO(self, record):
        return '\n'.join(self._textwrap_message(record))

    def DEBUG(self, record):
        message = record.getMessage()
        if self.printable_only and (not set(message).issubset(
                self._printable_chars)):
            message = "<<UNPRINTABLE>>"
        if __debug__:
            marker = self._colored(
                "[%s %s:%s]" % (record.levelname, record.name, record.lineno),
                'yellow')
        else:
            marker = "[%s]" % record.levelname
        return '%s %s' % (marker, message)

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
        except AttributeError:
            raise RuntimeError('Unknown record level (name: %s)' %
                               record.levelname)

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
        if self.allow_colors and color_args:
            return termcolor.colored(text, *color_args)
        else:
            return text

    def _msgbox(self, record, marker):
        width = self.line_width
        hline = self._colored(marker * width, 'red')
        parts = list(
            self._textwrap(
                [hline, '',
                 self._colored(record.levelname, 'cyan'), '']))
        parts.extend(self._textwrap_message(record))
        if parts[-1] != self.line_marker:
            parts.append(self.line_marker)
        parts.extend(self._textwrap([hline]))
        return '\n'.join(parts)

    def _textwrap_message(self, record):
        for line in record.getMessage().split('\n'):
            if self.printable_only and not set(line).issubset(
                    self._printable_chars):
                line = self._prune_ansi(line)
                line = "".join([c for c in line if c in self._printable_chars])
            if line:
                yield self._text_wrapper.fill(line)
            else:
                yield self.line_marker

    def _textwrap(self, lines):
        for line in lines:
            if line:
                yield self._text_wrapper.fill(line)
            else:
                yield self.line_marker


def get_logger(name):
    """Returns a customized logging object.
    
    Multiple calls to with the same name will always return a reference to the same Logger object.
    
    Args:
        name (str): Dot-separated hierarchical name for the logger.
        
    Returns:
        Logger: An instance of :any:`logging.Logger`.
    """
    return logging.getLogger(name)


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
    _STDOUT_HANDLER.setLevel(LOG_LEVEL)


LOG_LEVEL = 'INFO'
"""str: The global logging level for stdout loggers and software packages.

Don't change directly. May be changed via :any:`set_log_level`.  
"""

LOG_FILE = os.path.join(USER_PREFIX, 'debug_log')
"""str: Absolute path to a log file to receive all debugging output."""

LINE_MARKER = os.environ.get('E4S_LINE_MARKER', 'e4s')
"""str: Marker for each line of output."""

COLORED_LINE_MARKER = termcolor.colored(LINE_MARKER, 'red')

TERM_SIZE = get_terminal_size()
"""tuple: (width, height) tuple of detected terminal dimensions in characters."""

LINE_WIDTH = TERM_SIZE[0] - len(LINE_MARKER)
"""Width of a line on the terminal.

Uses system specific methods to determine console line width.  If the line
width cannot be determined, the default is 80.
"""

_ROOT_LOGGER = logging.getLogger()
if not _ROOT_LOGGER.handlers:
    _ROOT_LOGGER.setLevel(logging.DEBUG)
    _LOG_FILE_PREFIX = os.path.dirname(LOG_FILE)
    try:
        os.makedirs(_LOG_FILE_PREFIX)
    except OSError as exc:
        if not (exc.errno == errno.EEXIST and os.path.isdir(_LOG_FILE_PREFIX)):
            raise
    _STDOUT_HANDLER = logging.StreamHandler(sys.stderr)
    _STDOUT_HANDLER.setFormatter(
        LogFormatter(line_width=LINE_WIDTH, printable_only=False))
    _STDOUT_HANDLER.setLevel(LOG_LEVEL)
    _ROOT_LOGGER.addHandler(_STDOUT_HANDLER)
    _FILE_HANDLER = handlers.TimedRotatingFileHandler(LOG_FILE,
                                                      when='D',
                                                      interval=1,
                                                      backupCount=3)
    _FILE_HANDLER.setFormatter(LogFormatter(line_width=120,
                                            allow_colors=False))
    _FILE_HANDLER.setLevel(logging.DEBUG)
    _ROOT_LOGGER.addHandler(_FILE_HANDLER)
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
         "%(bar)s\n") % {
             'bar': '#' * LINE_WIDTH,
             'timestamp': str(datetime.now()),
             'hostname': socket.gethostname(),
             'platform': platform.platform(),
             'version': E4S_CL_VERSION,
             'pyversion': platform.python_version(),
             'cwd': os.getcwd(),
             'termsize': 'x'.join([str(_) for _ in TERM_SIZE]),
             'frozen': getattr(sys, 'frozen', False)
         })


def master_error(message):
    components = message.split(" ")
    if len(components) > 3 and components[0] == IDENTIFIER:
        with open("/tmp/e4s_cl/{}-{}.log".format(components[2], components[1]),
                  'a') as log_file:
            log_file.append(' '.join(components[3:]))
    else:
        sys.stderr.write(message)
