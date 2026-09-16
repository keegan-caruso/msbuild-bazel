"""Opt-in, process-local reuse of verified system-owned Nix store trees.

The Nix administrator/daemon and storage integrity are trusted for the session.
Mutable/user-owned trees always receive full hashing. No disk receipt authorizes
reuse. Restart the session after privileged store repair or administrative edits.
"""
import copy
import ctypes
import errno
import os
from pathlib import Path
import platform
import re
import stat
import threading


class ProtectedStore:
    def __init__(self):
        self.pid = os.getpid()
        self.cache = {}
        self.locks = {}
        self.lock = threading.Lock()
        self.full_reads = 0
        self.hits = 0
        self.bytes_avoided = 0
        self.libc = None
        if platform.system() == 'Darwin':
            self.libc = ctypes.CDLL(None, use_errno=True)
            self.libc.acl_get_link_np.argtypes = [ctypes.c_char_p, ctypes.c_int]
            self.libc.acl_get_link_np.restype = ctypes.c_void_p
            self.libc.acl_free.argtypes = [ctypes.c_void_p]

    def no_acl(self, path):
        if self.libc is None: return False
        ctypes.set_errno(0)
        acl = self.libc.acl_get_link_np(os.fsencode(path), 0x100)
        if acl:
            self.libc.acl_free(acl)
            return False
        # Darwin returns ENOENT when an existing vnode has no extended ACL.
        return ctypes.get_errno() == errno.ENOENT

    def protected(self, path, value):
        return (value.st_uid == 0 and
                (stat.S_ISLNK(value.st_mode) or not value.st_mode & 0o022) and
                self.no_acl(path))

    def eligible_root(self, root):
        if self.libc is None or os.geteuid() == 0 or self.pid != os.getpid(): return False
        if root.parent != Path('/nix/store') or not re.fullmatch('[0-9abcdfghijklmnpqrsvwxyz]{32}-.+',root.name): return False
        if root.is_symlink(): return False
        # Store entries are owned by root; the sticky store directory may allow
        # build users to add entries but not to replace root-owned generations.
        for parent in (Path('/'),Path('/nix'),Path('/nix/store')):
            value=parent.lstat()
            if value.st_uid != 0 or not self.no_acl(parent): return False
            if value.st_mode & 0o022 and not (parent == Path('/nix/store') and value.st_mode & stat.S_ISVTX): return False
        return self.protected(root,root.lstat())

    def snapshot(self, root, allowed):
        from preparation_identity import tree_snapshot, _signature
        root=Path(root).absolute()
        if not self.eligible_root(root): return tree_snapshot(root,allowed)
        key=(str(root),tuple(sorted(str(Path(p).resolve(strict=True)) for p in allowed)))
        with self.lock:
            lock=self.locks.setdefault(key,threading.Lock())
        with lock:
            current=_signature(root.lstat())
            saved=self.cache.get(key)
            if saved is not None and saved[0]==current:
                self.hits+=1;self.bytes_avoided+=saved[1]['bytesHashed']
                return copy.deepcopy(saved[1])
            eligible=True
            checked=set()
            def observe(path,value):
                nonlocal eligible
                if not path.is_relative_to('/nix/store'):
                    eligible=False
                    return
                if not self.protected(path,value): eligible=False
                for parent in path.parents:
                    if parent == Path('/nix/store'): break
                    if parent not in checked:
                        checked.add(parent)
                        if not self.protected(parent,parent.lstat()): eligible=False
            value=tree_snapshot(root,allowed,_observe=observe)
            self.full_reads+=1
            if eligible and _signature(root.lstat())==current:
                self.cache[key]=(current,copy.deepcopy(value))
            else:self.cache.pop(key,None)
            return value

    def statistics(self):
        return dict(fullReads=self.full_reads,hits=self.hits,bytesAvoided=self.bytes_avoided,roots=len(self.cache))
