PACKAGE = "e4s_cl"
VERSION = (1, 0, 2)
RELEASE_CANDIDATE = 0
__version__ = '.'.join(map(
    str, VERSION)) + (f"rc{RELEASE_CANDIDATE}" if RELEASE_CANDIDATE else '')
WEBSITE = 'https://e4s-cl.readthedocs.io'
LICENSE = 'MIT'
