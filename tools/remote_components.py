"""Bounded content-addressed preparation groups, independent of package objects."""
from concurrent.futures import ThreadPoolExecutor
import io
import stat
import zipfile

from preparation_identity import IdentityError
from portable_cache import fetch, sha, valid_path
from remote_packages import archive, upload


def describe(payload, excluded, endpoint):
    groups = {}
    for path in sorted(payload.rglob('*')):
        name = path.relative_to(payload).as_posix()
        if path.is_symlink(): raise IdentityError('linked preparation component')
        if not path.is_file() or 'payload/' + name in excluded: continue
        # Group authored sources by directory, keeping restore metadata separate.
        # A body edit does not retransmit sibling directories or graph metadata.
        key = ('source', str(path.relative_to(payload).parent)) if name.startswith('src/') else ('metadata', name.split('/')[0])
        groups.setdefault(key, []).append((name, path.read_bytes(), stat.S_IMODE(path.stat().st_mode)))
    def one(group):
        data = archive({name: content for name, content, mode in group})
        return dict(blob=upload(endpoint, data), files=[dict(path=name, size=len(content), sha256=sha(content), mode=mode) for name, content, mode in group])
    with ThreadPoolExecutor(max_workers=8) as pool: return list(pool.map(one, groups.values()))


def validate(records, occupied, remaining):
    if not isinstance(records, list) or len(records) > 10000: raise IdentityError('invalid preparation components')
    total = 0; members = set()
    def is_digest(value): return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)
    for record in records:
        if not isinstance(record, dict) or set(record) != {'blob', 'files'} or not is_digest(record['blob']) or not isinstance(record['files'], list):
            raise IdentityError('invalid preparation component')
        for item in record['files']:
            if (not isinstance(item, dict) or set(item) != {'path', 'size', 'sha256', 'mode'} or not valid_path(item['path']) or
                    type(item['size']) is not int or item['size'] < 0 or not is_digest(item['sha256']) or
                    type(item['mode']) is not int or not 0 <= item['mode'] <= 0o777): raise IdentityError('invalid component file')
            target = 'payload/' + item['path']; total += item['size']
            if target in occupied or target in members or total > remaining or len(members) >= 100000:
                raise IdentityError('overlapping or excessive component payload')
            members.add(target)
    # Reject file-as-parent collisions before touching the destination.
    for name in occupied | members:
        parts = name.split('/')
        if any('/'.join(parts[:end]) in members for end in range(1, len(parts))):
            raise IdentityError('component file overlaps directory')
    occupied.update(members)
    return total


def restore(endpoint, records, payload):
    if records and endpoint is None: raise IdentityError('preparation component endpoint required')
    def one(record):
        data = fetch(endpoint + '/cas/' + record['blob'])
        if len(data) > 64 * 1024 * 1024 or sha(data) != record['blob']: raise IdentityError('preparation component digest mismatch')
        expected = {item['path']: item for item in record['files']}; seen = set()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for member in z.infolist():
                item = expected.get(member.filename)
                if item is None or member.filename in seen or member.file_size != item['size']:
                    raise IdentityError('invalid preparation component member')
                contents = z.read(member)
                if sha(contents) != item['sha256']: raise IdentityError('preparation component file mismatch')
                seen.add(member.filename)
                path = payload / member.filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents); path.chmod(item['mode'])
        if seen != expected.keys(): raise IdentityError('incomplete preparation component')
    with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(one, records))
