"""Share SDK/tool snapshots within one invocation, then rehash before publication.

This is not a persistent receipt or a timestamp cache. Mutable source/discovery
views are never memoized. Every memoized root is checked again at successful
consumption exit; optional protected-store trust retains its existing semantics.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
from pathlib import Path
import stat
import threading

from preparation_identity import IdentityError, tree_snapshot


class InvocationIdentity:
    def __init__(self, controller_roots=(), protected_store=None):
        self.controller_roots = {str(Path(p).absolute()) for p in controller_roots}
        self.protected_store = protected_store
        self.policy = 'verified-invocation-v1' + ('+trusted-system-nix-session-v1' if protected_store is not None else '')
        self.saved = {}
        self.locks = {}
        self.lock = threading.Lock()
        self.closed = False
        self.hits = 0

    def snapshot(self, root, allowed):
        root = Path(root).absolute()
        if self.closed: raise IdentityError('identity invocation is closed')
        if str(root) not in self.controller_roots and root.parent != Path('/nix/store'):
            return tree_snapshot(root, allowed)
        key = str(root)
        with self.lock: lock = self.locks.setdefault(key, threading.Lock())
        with lock:
            if key not in self.saved:
                boundaries = {root.resolve(strict=True)}
                def observe(path, value):
                    if stat.S_ISLNK(value.st_mode): boundaries.add(path.resolve(strict=True))
                # Keep the existing explicit administrator-trust path separate.
                # Its memoization already validates the exact allowed-root set.
                if self.protected_store is not None and root.parent == Path('/nix/store'):
                    return self.protected_store.snapshot(root, allowed)
                value = tree_snapshot(root, allowed, _observe=observe)
                self.saved[key] = (value, boundaries, list(allowed))
            else: self.hits += 1
            value, boundaries, _ = self.saved[key]
            roots = [Path(p).resolve(strict=True) for p in allowed]
            # A broad SDK fingerprint may be shared with a narrower discovery
            # closure only if every resolved traversal boundary is admitted.
            if any(not any(path == parent or path.is_relative_to(parent) for parent in roots) for path in boundaries):
                raise IdentityError('memoized identity has an undeclared symlink target')
            return copy.deepcopy(value)

    def verify(self):
        if self.closed: raise IdentityError('identity invocation is closed')
        self.closed = True
        def check(saved):
            value, _, allowed = saved
            current = tree_snapshot(value['location'], allowed)
            if current != value:
                raise IdentityError('SDK or controller inputs changed during consumption')
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(self.saved)))) as workers:
            list(workers.map(check, self.saved.values()))
