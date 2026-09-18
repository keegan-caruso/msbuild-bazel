"""Content-checked synchronization of an owned generated Bazel workspace.

No persisted stat receipt authorizes reuse. Every desired file is compared with
its current bytes; unchanged files retain their inode/mtime. Links are never
followed when writing or pruning the managed inputs.
"""
from pathlib import Path
import os
import tempfile


class Staging:
    def __init__(self, root):
        self.root = Path(root)
        if self.root.is_symlink(): raise ValueError('linked generated workspace')
        self.root.mkdir(parents=True, exist_ok=True)
        self.desired = set()
        self.written = 0
        self.retained = 0

    def write(self, relative, data):
        relative = Path(relative)
        if relative.is_absolute() or '..' in relative.parts: raise ValueError('unsafe generated path')
        path = self.root / relative
        for parent in reversed(path.parents):
            if parent == self.root or self.root in parent.parents:
                if parent.is_symlink(): raise ValueError('linked generated input directory')
                parent.mkdir(exist_ok=True)
        self.desired.add(relative.as_posix())
        if path.is_symlink(): raise ValueError('linked generated input')
        if path.is_file() and path.read_bytes() == data:
            self.retained += 1
            return
        descriptor, temporary = tempfile.mkstemp(prefix='.stage-', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream: stream.write(data)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        self.written += 1

    def copy(self, source, relative):
        self.write(relative, Path(source).read_bytes())

    def tree(self, source, relative):
        for path in sorted(Path(source).rglob('*')):
            if path.is_symlink(): raise ValueError('linked staging source')
            if path.is_file(): self.copy(path, Path(relative) / path.relative_to(source))

    def finish(self):
        # Bazel owns these convenience links and its module lock. All other
        # inputs are derived again, so removed sources/seeds cannot survive.
        retained = {'MODULE.bazel.lock', 'bazel-bin', 'bazel-out', 'bazel-testlogs', 'bazel-' + self.root.name}
        def prune(directory):
            for path in directory.iterdir():
                relative = path.relative_to(self.root).as_posix()
                if directory == self.root and relative in retained: continue
                if path.is_symlink():
                    path.unlink()
                elif path.is_dir():
                    prune(path)
                    if not any(path.iterdir()): path.rmdir()
                elif relative not in self.desired: path.unlink()
        prune(self.root)
        return dict(written=self.written, retained=self.retained)
