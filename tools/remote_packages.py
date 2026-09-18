"""Content-addressed package payloads with verified NuGet-cache reconstruction."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import stat
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

from portable_cache import fetch, put, sha, valid_path
from preparation_identity import IdentityError

MAX_PACKAGE = 64 * 1024 * 1024


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    result = buffer.getvalue()
    if len(result) > MAX_PACKAGE: raise IdentityError('remote package archive exceeds limit')
    return result


def upload(endpoint, data):
    key = sha(data)
    # HEAD avoids sending unchanged package bytes. Older GET/PUT-only services
    # remain supported, with redundant PUTs rather than trusting an old receipt.
    try:
        with urlopen(Request(endpoint + '/cas/' + key, method='HEAD'), timeout=5) as response:
            if response.status == 200 and response.headers.get('Content-Length') == str(len(data)): return key
    except HTTPError as error:
        if error.code not in (404, 405, 501): raise
    put(endpoint + '/cas/' + key, data)
    return key


def describe(payload, endpoint=None):
    manifests = {}
    for path in sorted((payload / 'package-manifests').glob('*.json')):
        for package in json.loads(path.read_text())['packages']:
            relative = package['path']
            description = dict(archiveSha256=package['archiveSha256'], files={f['path']: (f['size'], f['sha256']) for f in package['files']})
            previous = manifests.setdefault(relative, description)
            if previous != description: raise IdentityError('conflicting package manifests')
    records = []
    def one(relative):
        folder = payload / 'src/.nuget/packages' / relative
        files = {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob('*')) if p.is_file()}
        expected = manifests[relative]['files']
        if files.keys() != expected.keys() or any((len(data), sha(data)) != expected[name] for name, data in files.items()):
            raise IdentityError('prepared package differs from verified manifest')
        data = archive(files)
        blob = upload(endpoint, data) if endpoint else sha(data)
        entries = [dict(path=name, size=len(content), sha256=sha(content), mode=stat.S_IMODE((folder / name).stat().st_mode)) for name, content in files.items()]
        return dict(path=relative, archiveSha256=manifests[relative]['archiveSha256'], blob=blob, files=entries)
    with ThreadPoolExecutor(max_workers=8) as pool: records = list(pool.map(one, sorted(manifests)))
    return records


def read_local(root, relative):
    path = root / relative
    if not valid_path(relative) or any(p.is_symlink() for p in [path, *path.parents] if p != root and p.is_relative_to(root)):
        raise IdentityError('linked or invalid NuGet cache input')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        value = os.fstat(stream.fileno())
        if not stat.S_ISREG(value.st_mode) or value.st_size > 512 * 1024 * 1024: raise IdentityError('invalid NuGet cache file')
        data = stream.read(512 * 1024 * 1024 + 1)
        if len(data) > 512 * 1024 * 1024: raise IdentityError('NuGet cache file exceeds limit')
        return data


def local_files(root, record):
    folder = record['path']; package_id, version = folder.split('/')
    compressed = None; extracted = None; result = {}
    def package():
        nonlocal compressed, extracted
        if compressed is None:
            compressed = read_local(root, folder + '/' + package_id + '.' + version + '.nupkg')
            if sha(compressed) != record['archiveSha256']: raise IdentityError('NuGet archive differs from preparation')
            extracted = {}
            with zipfile.ZipFile(io.BytesIO(compressed)) as z:
                total = 0
                for item in z.infolist():
                    if item.is_dir(): continue
                    total += item.file_size
                    name = item.filename.replace('%2B', '+').replace('%2b', '+')
                    if name.endswith('.nuspec'): name = name.lower()
                    if total > 512 * 1024 * 1024 or not valid_path(name) or name in extracted: raise IdentityError('invalid NuGet archive')
                    # Only archive bookkeeping omitted by NuGet is reconstructed.
                    if name in ('_rels/.rels', '[Content_Types].xml') or name.startswith('package/services/metadata/core-properties/'):
                        extracted[name] = z.read(item)
        return compressed, extracted
    for item in record['files']:
        name = item['path']
        if name == package_id + '.' + version + '.nupkg.sha512':
            data = base64.b64encode(hashlib.sha512(package()[0]).digest())
        else:
            try: data = read_local(root, folder + '/' + name)
            except FileNotFoundError:
                data = package()[1].get(name)
                if data is None: raise IdentityError('missing extracted NuGet payload: ' + name)
        if len(data) != item['size'] or sha(data) != item['sha256']: raise IdentityError('NuGet payload differs from preparation: ' + name)
        result[name] = data
    return result


def restore(endpoint, records, payload, cache_roots):
    def one(record):
        errors = []
        for root in cache_roots:
            try: return record, local_files(Path(root).resolve(), record), True, errors
            except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error: errors.append(str(error))
        if endpoint is None: raise IdentityError('package bytes unavailable locally')
        data = fetch(endpoint + '/cas/' + record['blob'])
        if len(data) > MAX_PACKAGE or sha(data) != record['blob']: raise IdentityError('remote package digest mismatch')
        expected = {item['path']: item for item in record['files']}
        files = {}
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for member in z.infolist():
                item = expected.get(member.filename)
                if item is None or member.filename in files or member.file_size != item['size']: raise IdentityError('invalid remote package member')
                contents = z.read(member)
                if sha(contents) != item['sha256']: raise IdentityError('remote package payload corrupt')
                files[member.filename] = contents
        if files.keys() != expected.keys(): raise IdentityError('incomplete remote package')
        return record, files, False, errors
    receipts = dict(localPackages=0, remotePackages=0, localBytes=0, localRejections=[])
    with ThreadPoolExecutor(max_workers=8) as pool:
        for record, files, local, errors in pool.map(one, records):
            for item in record['files']:
                path = payload / 'src/.nuget/packages' / record['path'] / item['path']
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(files[item['path']]); path.chmod(item['mode'])
            receipts['localPackages' if local else 'remotePackages'] += 1
            if local: receipts['localBytes'] += sum(len(data) for data in files.values())
            elif errors: receipts['localRejections'].append(dict(package=record['path'], reasons=errors))
    return receipts


def validate(records, occupied, remaining):
    if not isinstance(records, list) or len(records) > 10000: raise IdentityError('invalid package records')
    seen = set(); members = set(); total = 0
    def is_digest(value): return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)
    for record in records:
        if (not isinstance(record, dict) or set(record) != {'path', 'archiveSha256', 'blob', 'files'} or
                not valid_path(record['path']) or len(record['path'].split('/')) != 2 or record['path'] in seen or
                not is_digest(record['blob']) or not is_digest(record['archiveSha256']) or not isinstance(record['files'], list)):
            raise IdentityError('invalid package record')
        seen.add(record['path'])
        for item in record['files']:
            if (not isinstance(item, dict) or set(item) != {'path', 'size', 'sha256', 'mode'} or not valid_path(item['path']) or
                    type(item['size']) is not int or item['size'] < 0 or not is_digest(item['sha256']) or
                    type(item['mode']) is not int or not 0 <= item['mode'] <= 0o777): raise IdentityError('invalid package file')
            target = 'payload/src/.nuget/packages/' + record['path'] + '/' + item['path']
            total += item['size']
            if target in occupied or target in members or total > remaining or len(members) >= 100000:
                raise IdentityError('overlapping or excessive package payload')
            members.add(target)
    return total
