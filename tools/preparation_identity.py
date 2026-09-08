"""Versioned, conservative discovery snapshots; not a cache reuse authorization.

Callers supply the complete supported read domain. Nothing is excluded implicitly:
new files/directories, optional inputs and restored payloads all participate. A
matching snapshot cannot prove that arbitrary MSBuild property functions never
read undeclared host state. The separate discovery contract enforces eligibility;
RUL-6 owns reuse and publication.
"""
import hashlib
import json
import os
from pathlib import Path
import stat

SCHEMA_VERSION = 1
POLICY = 'content-declared-trees-v1'


class IdentityError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _signature(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def tree_snapshot(root, allowed_roots=None):
    """Hash bytes and namespace membership, rejecting unstable/escaping inputs.

    Root locations are deliberately bound to this host/path. Directory names and
    modes participate even when empty. Timestamps only detect unstable reads; they are not persistent identity.
    Timestamp-sensitive evaluation is ineligible until deterministic staging is
    enforced. This traversal is not an atomic filesystem snapshot.
    """
    root = Path(root).absolute()
    try:
        allowed = [Path(path).resolve(strict=True) for path in (allowed_roots or [root])]
    except (OSError, RuntimeError) as error:
        raise IdentityError('missing or unreadable discovery input: ' + str(root)) from error
    records = []
    total_bytes = 0
    observed = []

    def visit(path, logical, ancestors):
        nonlocal total_bytes
        before = path.lstat()
        mode = stat.S_IMODE(before.st_mode)
        resolved = path.resolve(strict=True)
        if not any(resolved == domain or resolved.is_relative_to(domain) for domain in allowed):
            raise IdentityError('undeclared symlink target: ' + logical)
        if stat.S_ISLNK(before.st_mode):
            target = os.readlink(path)
            records.append(dict(path=logical, kind='symlink', target=target))
            if resolved in ancestors:
                raise IdentityError('symlink cycle: ' + logical)
            visit(resolved, logical + '/@target', ancestors)
        elif stat.S_ISDIR(before.st_mode):
            if resolved in ancestors:
                raise IdentityError('directory cycle: ' + logical)
            records.append(dict(path=logical, kind='directory', mode=mode))
            names = sorted(os.listdir(path))
            for name in names:
                visit(path / name, logical + '/' + name, ancestors | {resolved})
            if names != sorted(os.listdir(path)):
                raise IdentityError('directory changed while reading: ' + logical)
        elif stat.S_ISREG(before.st_mode):
            hasher = hashlib.sha256()
            size = 0
            with path.open('rb') as stream:
                if _signature(before) != _signature(os.fstat(stream.fileno())):
                    raise IdentityError('file changed before reading: ' + logical)
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    hasher.update(chunk)
                    size += len(chunk)
                if _signature(before) != _signature(os.fstat(stream.fileno())):
                    raise IdentityError('file changed while reading: ' + logical)
            records.append(dict(path=logical, kind='file', mode=mode, size=size, sha256=hasher.hexdigest()))
            total_bytes += size
        else:
            raise IdentityError('unsupported filesystem entry: ' + logical)
        observed.append((path, _signature(before)))
        if _signature(before) != _signature(path.lstat()):
            raise IdentityError('entry changed while reading: ' + logical)

    try:
        visit(root, '.', set())
        for path, signature in observed:
            if signature != _signature(path.lstat()):
                raise IdentityError('entry changed during traversal: ' + str(path))
    except (OSError, RuntimeError) as error:
        raise IdentityError('missing or unreadable discovery input: ' + str(root)) from error
    return dict(location=str(root), resolvedLocation=str(root.resolve()),
        sha256=digest(records), entries=records, bytesHashed=total_bytes)


def capture(roots, *, request, environment, host, schema=SCHEMA_VERSION):
    """Return a content identity for explicitly enumerated discovery domains.

    Environment values are hashed as a whole, never included in reports. The
    caller passes the effective environment, not merely changed overrides.
    Request fields are retained verbatim for hashing: unknown fields are not
    silently dropped and path relocation intentionally invalidates the key.
    """
    if schema != SCHEMA_VERSION:
        raise IdentityError('unsupported discovery identity schema')
    if not roots or any(not isinstance(name, str) or not name for name in roots):
        raise IdentityError('named discovery roots are required')
    allowed = []
    for path in roots.values():
        try:
            allowed.append(Path(path).resolve(strict=True))
        except (OSError, RuntimeError) as error:
            raise IdentityError('missing discovery root') from error
    snapshots = {name: tree_snapshot(path, allowed) for name, path in sorted(roots.items())}
    key_fields = dict(schemaVersion=schema, policy=POLICY,
        roots={name: {key: value for key, value in snapshot.items()
            if key in ('location', 'resolvedLocation', 'sha256')} for name, snapshot in snapshots.items()},
        requestSha256=digest(request), environmentSha256=digest(environment), hostSha256=digest(host))
    return dict(**key_fields, key=digest(key_fields), snapshots=snapshots)


def validate(value):
    """Reject incomplete or internally inconsistent persisted snapshots."""
    try:
        fields = {name: value[name] for name in ('schemaVersion', 'policy', 'roots',
            'requestSha256', 'environmentSha256', 'hostSha256')}
        if fields['schemaVersion'] != SCHEMA_VERSION or fields['policy'] != POLICY:
            raise IdentityError('unsupported discovery identity schema or policy')
        if not fields['roots'] or not isinstance(fields['roots'], dict):
            raise IdentityError('corrupt discovery identity')
        if value['key'] != digest(fields) or set(value['snapshots']) != set(fields['roots']):
            raise IdentityError('corrupt discovery identity')
        for name, root in fields['roots'].items():
            snapshot = value['snapshots'][name]
            if root != {key: snapshot[key] for key in ('location', 'resolvedLocation', 'sha256')}:
                raise IdentityError('corrupt discovery identity')
            if snapshot['sha256'] != digest(snapshot['entries']):
                raise IdentityError('corrupt discovery identity')
            if snapshot['bytesHashed'] != sum(entry.get('size', 0) for entry in snapshot['entries']):
                raise IdentityError('corrupt discovery identity')
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        if isinstance(error, IdentityError):
            raise
        raise IdentityError('corrupt discovery identity') from error


def compare(previous, current):
    """Report changes within declared domains; matching keys do not authorize reuse."""
    for value in (previous, current):
        validate(value)
    changes = [name for name in ('requestSha256', 'environmentSha256', 'hostSha256')
               if previous[name] != current[name]]
    changes += ['root:' + name for name in sorted(previous['roots'].keys() | current['roots'].keys())
                if previous['roots'].get(name) != current['roots'].get(name)]
    return dict(unchanged=not changes, changedDomains=changes)
