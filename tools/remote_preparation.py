"""Portable native preparation from an explicitly pinned, trusted CAS snapshot.

Relocation is a new proof, not permission to ignore path-bound identity fields.
Only known restore metadata is normalized; all namespace/mode/content checks,
tool/runtime trees, selected invocation and compatible host facts remain bound.
"""
import copy
import io
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import zipfile

import discovery_contract as discovery
import remote_packages
import remote_components
from preparation_identity import IdentityError, digest
from preparation_reuse import payload_identity
from portable_cache import fetch, put, sha, valid_path

POLICY = 'portable-native-preparation-v3'
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_PAYLOAD = 512 * 1024 * 1024


def host():
    return dict(platform=platform.platform(), machine=platform.machine(),
                osBuild=subprocess.check_output(['/usr/bin/sw_vers', '-buildVersion'], text=True).strip(),
                bootSession=subprocess.check_output(['/usr/sbin/sysctl', '-n', 'kern.bootsessionuuid'], text=True).strip(),
                cpuCount=os.cpu_count())


def portable_request(request):
    result = copy.deepcopy(request)
    trees = result['tools']['trees']
    roles = {Path(path).name: value for path, value in trees.items()}
    if len(roles) != len(trees): raise IdentityError('ambiguous controller roles')
    result['tools']['trees'] = roles
    return result


def restore_file(path):
    return 'obj' in path.parts and (path.name in ('project.assets.json', 'project.nuget.cache') or
        path.name.endswith(('.nuget.g.props', '.nuget.g.targets', '.nuget.dgspec.json')))


def portable_entries(workspace, snapshot):
    entries = copy.deepcopy(snapshot['entries'])
    for item in entries:
        relative = Path(item['path'])
        if item['kind'] != 'file' or not restore_file(relative): continue
        path = workspace / relative
        data = path.read_bytes()
        if sha(data) != item['sha256'] or len(data) != item['size']:
            raise IdentityError('restore input changed during portable capture')
        data = data.replace(str(workspace).encode(), b'${WORKSPACE}')
        if path.name == 'project.nuget.cache':
            receipt = json.loads(data)
            if receipt.get('success') is not True: raise IdentityError('unsuccessful restore receipt')
            # Match GraphExport/prepare_graph's existing normalization. Preserve
            # every other receipt field, all assets, and every dependency spec.
            if 'dgSpecHash' in receipt: receipt['dgSpecHash'] = '$NORMALIZED'
            data = json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode()
        item.update(size=len(data), sha256=sha(data))
    return entries


def context_hashes(identity, entries):
    roots = identity['roots']
    workspace = Path(roots['workspace']['location'])
    base = workspace.parent
    names = ['workspace'] + sorted((name for name in roots if name.startswith('runtime-')), key=lambda name: int(name[8:])) + ['GraphExport', 'EvaluationProbe']
    if set(names) != set(roots): raise IdentityError('unsupported discovery roots')
    for name in ('GraphExport', 'EvaluationProbe'):
        if roots[name]['location'] != str(base / 'tools' / name): raise IdentityError('unexpected discovery tool layout')
    profile = discovery.sandbox_profile([Path(roots[name]['location']) for name in names] + [base / 'output'], base / 'output')
    request = dict(policy=discovery.POLICY, timestampEpoch=discovery.EPOCH, entries=entries,
                   sandboxSha256=digest(profile), contractSha256=discovery.CONTROLLER_DIGEST)
    return digest(request), digest(discovery.controlled_environment(base / 'output'))


def identity_with_workspace(current, entries):
    result = copy.deepcopy(current)
    snapshot = result['snapshots']['workspace']
    snapshot.update(entries=entries, sha256=digest(entries), bytesHashed=sum(item.get('size', 0) for item in entries))
    result['roots']['workspace']['sha256'] = snapshot['sha256']
    result['key'] = digest({key: value for key, value in result.items() if key not in ('key', 'snapshots')})
    return result


def rebase(metadata, current, current_host):
    previous = metadata['certificate']
    discovery.validate_certificate(previous)
    old = previous['identity']
    for identity in (old, current):
        request, environment = context_hashes(identity, metadata['request']['entries'])
        if identity['requestSha256'] != request or identity['environmentSha256'] != environment:
            raise IdentityError('portable discovery invocation mismatch')
    if digest(metadata['host']) != old['hostSha256'] or digest(current_host) != current['hostSha256']:
        raise IdentityError('portable host evidence mismatch')
    if {k: v for k, v in metadata['host'].items() if k != 'bootSession'} != {k: v for k, v in current_host.items() if k != 'bootSession'}:
        raise IdentityError('incompatible preparation host')
    if old['roots'].keys() != current['roots'].keys(): raise IdentityError('discovery domains changed')
    for name, root in old['roots'].items():
        if name == 'workspace': continue
        actual = current['roots'][name]
        if root['sha256'] != actual['sha256'] or name.startswith('runtime-') and root != actual:
            raise IdentityError('discovery tool/runtime changed')
    old_workspace = Path(old['roots']['workspace']['location'])
    workspace = Path(current['roots']['workspace']['location'])
    # Ancestor lookups are part of the selected SDK behavior. This first portable
    # policy keeps the same nesting depth and rechecks every relocated absence.
    if len(old_workspace.parts) != len(workspace.parts): raise IdentityError('different discovery ancestor layout')
    ancestors = dict(zip(old_workspace.parents, workspace.parents))
    absent = []
    for value in previous['externalAbsent']:
        path = Path(value)
        if path.parent in ancestors: path = ancestors[path.parent] / path.name
        if path.exists(): raise IdentityError('relocated external input exists: ' + str(path))
        absent.append(str(path))
    prior = {entry['path']: entry for entry in metadata['workspaceEntries']}
    actual = {entry['path']: entry for entry in portable_entries(workspace, current['snapshots']['workspace'])}
    if prior.keys() != actual.keys(): raise IdentityError('workspace namespace changed')
    entries = copy.deepcopy(old['snapshots']['workspace']['entries'])
    current_entries = {entry['path']: entry for entry in current['snapshots']['workspace']['entries']}
    for entry in entries:
        path = entry['path']
        if restore_file(Path(path)):
            if prior[path] != actual[path]: raise IdentityError('restore inputs changed')
            entry.update(current_entries[path])
    certificate = copy.deepcopy(previous)
    certificate.update(identity=identity_with_workspace(current, entries), externalAbsent=sorted(absent),
                       relocation=dict(policy=POLICY, parentCertificate=previous['sha256']))
    certificate['sha256'] = digest({k: v for k, v in certificate.items() if k != 'sha256'})
    discovery.validate_certificate(certificate)
    return certificate


def split_evidence(metadata, endpoint):
    # Only transport changes: restore exact entries before certificate validation.
    snapshots = metadata['certificate']['identity']['snapshots']
    entries = {name: value.pop('entries') for name, value in snapshots.items() if name != 'workspace'}
    data = remote_packages.archive({'entries.json': json.dumps(entries, sort_keys=True).encode()})
    metadata['evidence'] = remote_packages.upload(endpoint, data)


def hydrate_evidence(metadata, endpoint):
    blob = metadata.pop('evidence', None)
    if blob is None: return
    if not isinstance(blob, str) or len(blob) != 64 or any(c not in '0123456789abcdef' for c in blob) or endpoint is None:
        raise IdentityError('invalid remote evidence reference')
    data = fetch(endpoint + '/cas/' + blob)
    if len(data) > MAX_ARCHIVE or sha(data) != blob: raise IdentityError('remote evidence digest mismatch')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) != 1 or members[0].filename != 'entries.json' or members[0].file_size > MAX_ARCHIVE:
            raise IdentityError('invalid remote evidence object')
        entries = json.loads(archive.read(members[0]))
    snapshots = metadata['certificate']['identity']['snapshots']
    if not isinstance(entries, dict) or set(entries) != set(snapshots) - {'workspace'}:
        raise IdentityError('remote evidence domains differ')
    for name, value in entries.items():
        if 'entries' in snapshots[name] or not isinstance(value, list): raise IdentityError('overlapping remote evidence')
        snapshots[name]['entries'] = value


def pack(generation, *, endpoint=None):
    manifest = json.loads((generation / 'manifest.json').read_text())
    certificate = manifest['certificate']
    discovery.validate_certificate(certificate)
    if payload_identity(generation / 'payload') != manifest['payloadSha256']: raise IdentityError('prepared payload changed before upload')
    facts = host()
    if digest(facts) != certificate['identity']['hostSha256']: raise IdentityError('host changed before upload')
    metadata = dict(policy=POLICY, request=portable_request(manifest['request']), certificate=certificate,
                    host=facts, payloadSha256=manifest['payloadSha256'], payloadMode=stat.S_IMODE((generation / 'payload').stat().st_mode),
                    workspaceEntries=portable_entries(Path(certificate['identity']['roots']['workspace']['location']), certificate['identity']['snapshots']['workspace']))
    metadata['packages'] = remote_packages.describe(generation / 'payload', endpoint)
    package_files = {'payload/src/.nuget/packages/' + p['path'] + '/' + f['path'] for p in metadata['packages'] for f in p['files']}
    metadata['components'] = remote_components.describe(generation / 'payload', package_files, endpoint) if endpoint else []
    component_files = {'payload/' + f['path'] for c in metadata['components'] for f in c['files']}
    if endpoint: split_evidence(metadata, endpoint)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        info = zipfile.ZipInfo('remote.json', date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, json.dumps(metadata, sort_keys=True))
        for path in sorted((generation / 'payload').rglob('*')):
            if path.is_symlink(): raise IdentityError('linked remote preparation payload')
            name = path.relative_to(generation).as_posix() + ('/' if path.is_dir() else '')
            if name in package_files or name in component_files: continue
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = path.stat().st_mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, b'' if path.is_dir() else path.read_bytes())
    if payload_identity(generation / 'payload') != manifest['payloadSha256']: raise IdentityError('prepared payload changed during upload packing')
    data = buffer.getvalue()
    if len(data) > MAX_ARCHIVE: raise IdentityError('remote preparation archive exceeds limit')
    return data


def unpack(data, destination, request, *, endpoint=None, cache_roots=()):
    if len(data) > MAX_ARCHIVE: raise IdentityError('remote preparation archive exceeds limit')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(); total = 0; directories = []
        for item in archive.infolist():
            name = item.filename.rstrip('/')
            total += item.file_size
            mode = item.external_attr >> 16
            if (not valid_path(name) or name in names or total > MAX_PAYLOAD or len(names) >= 100000 or
                    stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or mode & 0o7000 or
                    name != 'remote.json' and not name.startswith('payload/')):
                raise IdentityError('invalid preparation archive member')
            names.add(name)
        metadata = json.loads(archive.read('remote.json'))
        if not isinstance(metadata, dict) or metadata.get('policy') != POLICY or metadata.get('request') != portable_request(request):
            raise IdentityError('remote preparation request changed')
        hydrate_evidence(metadata, endpoint)
        discovery.validate_certificate(metadata['certificate'])
        if not isinstance(metadata.get('host'), dict) or not isinstance(metadata.get('workspaceEntries'), list):
            raise IdentityError('invalid portable evidence')
        original = metadata['certificate']['identity']['snapshots']['workspace']['entries']
        normalized = metadata['workspaceEntries']
        if len(original) != len(normalized): raise IdentityError('portable workspace evidence differs')
        for old, new in zip(original, normalized):
            if not isinstance(new, dict): raise IdentityError('invalid portable workspace entry')
            ignored = ('size', 'sha256') if old['kind'] == 'file' and restore_file(Path(old['path'])) else ()
            if {k: v for k, v in old.items() if k not in ignored} != {k: v for k, v in new.items() if k not in ignored}:
                raise IdentityError('portable workspace evidence differs')
        if type(metadata.get('payloadMode')) is not int or not 0 <= metadata['payloadMode'] <= 0o777:
            raise IdentityError('invalid preparation root mode')
        total += remote_components.validate(metadata.get('components'), names, MAX_PAYLOAD - total)
        remote_packages.validate(metadata.get('packages'), names, MAX_PAYLOAD - total)
        destination.mkdir()
        for item in archive.infolist():
            if item.filename == 'remote.json': continue
            path = destination / item.filename
            if item.is_dir(): path.mkdir(parents=True, exist_ok=True); directories.append((path, (item.external_attr >> 16) & 0o777))
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(item)); path.chmod((item.external_attr >> 16) & 0o777)
        for path, mode in reversed(directories): path.chmod(mode)
    remote_components.restore(endpoint, metadata['components'], destination / 'payload')
    metadata['packageReuse'] = remote_packages.restore(endpoint, metadata['packages'], destination / 'payload', cache_roots)
    (destination / 'payload').chmod(metadata['payloadMode'])
    discovery.validate_certificate(metadata['certificate'])
    if payload_identity(destination / 'payload') != metadata['payloadSha256']: raise IdentityError('remote preparation payload corrupt')
    graph = json.loads((destination / 'payload/graph.json').read_text())
    if digest(graph) != metadata['certificate']['graphSha256']: raise IdentityError('remote graph/certificate mismatch')
    return metadata


def download(endpoint, blob, destination, request, *, cache_roots=()):
    data = fetch(endpoint + '/cas/' + blob)
    if sha(data) != blob: raise IdentityError('remote preparation digest mismatch')
    return unpack(data, destination, request, endpoint=endpoint, cache_roots=cache_roots)


def upload(endpoint, generation):
    data = pack(generation, endpoint=endpoint); blob = sha(data)
    put(endpoint + '/cas/' + blob, data)
    return blob
