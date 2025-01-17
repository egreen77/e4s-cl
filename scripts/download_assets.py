#!/bin/env python3
"""
Script downloading and decompressing precompiled binaries and prebuilt profiles \
from a given URL and adding them to e4s-cl's database
"""

import os
import stat
import sys
import lzma
from pathlib import Path
from requests import get

from e4s_cl import logger, USER_PREFIX
from e4s_cl.cf.storage.levels import highest_writable_storage
from e4s_cl.cf.assets import (add_builtin_profile, add_precompiled_binary,
                              SAMPLE_BINARY_TABLE)

LOGGER = logger.get_logger(__name__)

BINARY_DIR = Path(highest_writable_storage().prefix(), SAMPLE_BINARY_TABLE)


def init_dirs():
    BINARY_DIR.mkdir(parents=True, exist_ok=True)


def download_binaries(url: str, available: dict) -> None:
    """
    From a dict of {soname, suffix.xz} download and uncompress from the provided URL
    """
    for library, binary in available.items():
        bin_url = f"{url}/{binary}"
        destination = Path(BINARY_DIR, Path(binary).stem)

        answer = get(bin_url)

        if not answer.ok:
            LOGGER.warning("Failed to access %s", bin_url)
            continue

        with open(destination, "wb") as decompressed:
            compressed_data = lzma.LZMADecompressor()

            for chunk in answer.iter_content(chunk_size=8192):
                decompressed.write(compressed_data.decompress(chunk))

        status = os.stat(destination)
        os.chmod(destination, status.st_mode | stat.S_IEXEC)

        add_precompiled_binary(library, destination.as_posix())


def download_profile(url: str, available: dict, system: str) -> None:
    """
    If a profile url is returned, download and put its JSON file in the profile directory
    """
    if not available or not available.get(system):
        LOGGER.error("Failed to locate a profile for system '%s', skipping ..",
                     system)
        return

    suffix = available.get(system)

    profile_url = f"{url}/{suffix}"
    answer = get(profile_url)

    if not answer.ok:
        LOGGER.warning("Failed to access %s", profile_url)
        return

    add_builtin_profile(system, answer.json())


def main():
    """
    Check command line, ensure directories are created, query index and download
    """
    if len(sys.argv) < 3:
        LOGGER.error("Usage: %s <URL> <architecture> [system]", sys.argv[0])
        sys.exit(1)

    init_dirs()

    url, architecture = sys.argv[1:3]
    system = ''
    if len(sys.argv) > 3:
        system = sys.argv[3]

    index = get(f"{url}/index.json")

    if not index.ok:
        LOGGER.error("Failed to download data from %s. Is the URL correct ?",
                     url)

    available = index.json()

    download_binaries(url, available.get('binaries', {}).get(architecture, {}))
    if system:
        download_profile(url, available.get('profiles', {}), system)


if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        __file__ = sys.executable

    main()
