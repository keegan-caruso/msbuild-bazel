"""Explicit Ubuntu AppArmor launcher handoff with declared byte identity."""
import hashlib
from pathlib import Path
import stat
import sys

SYSTEM_BWRAP = Path('/usr/bin/bwrap')


def select_sandbox(declared, system_bwrap=False):
    if not system_bwrap:
        return declared
    if sys.platform != 'linux':
        raise ValueError('--system-bwrap requires Linux')
    # The packaged launcher and its containing OS directories must be trusted.
    # This is an explicit host prerequisite, never an alternate tool input.
    for path in [Path('/'), Path('/usr'), Path('/usr/bin'), SYSTEM_BWRAP]:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise ValueError('System Bubblewrap paths must be root-owned, non-symlink and not group/other writable: ' + str(path))
    if not SYSTEM_BWRAP.is_file() or not SYSTEM_BWRAP.stat().st_mode & 0o100:
        raise ValueError('System Bubblewrap is not executable: ' + str(SYSTEM_BWRAP))
    expected = hashlib.sha256(Path(declared).read_bytes()).hexdigest()
    actual = hashlib.sha256(SYSTEM_BWRAP.read_bytes()).hexdigest()
    if expected != actual:
        raise ValueError('System Bubblewrap SHA-256 differs from declared input (declared ' + expected + ', /usr/bin/bwrap ' + actual + '). Install the pinned Bubblewrap package or omit --system-bwrap on a host permitting the declared launcher.')
    return SYSTEM_BWRAP
