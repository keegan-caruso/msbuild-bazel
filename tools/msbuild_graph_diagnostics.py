"""Diagnose verified graph-snapshot XML; this is not a discovery eligibility gate."""
import hashlib
import json
from pathlib import Path, PurePosixPath

from check_msbuild_time import scan

ROOT = Path(__file__).resolve().parents[1]
TEXT_IMPORTS = {'.json', '.props', '.targets', '.xml', '.proj', '.csproj'}


def import_text(raw):
    # Match File.ReadAllText's BOM detection without changing CR/LF bytes.
    if raw.startswith((b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff')):
        return raw.decode('utf-32')
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16')
    return raw.decode('utf-8-sig')


def scan_graph(request_path):
    report = dict(schemaVersion=1, scope='msbuild-evaluated-import-time-diagnostics',
        reuseEnabled=False, eligibility='not-established', files=[], findings=[],
        coverageGaps=[], errors=[], inventoryVerified=False)
    try:
        request = json.loads(Path(request_path).read_text())
        graph = json.loads(Path(request['output']).read_text())
        if request['schemaVersion'] != 1 or graph['schemaVersion'] != 1:
            raise ValueError('unsupported graph/request schema')
        if graph['toolchain']['sdkVersion'] != request['sdkVersion']:
            raise ValueError('graph/request SDK mismatch')
        def entries(values):
            return sorted((v['project'], sorted((k.lower(), value) for k, value in v['globalProperties'].items())) for v in values)
        if entries(request['entryPoints']) != entries(graph['entryRequests']):
            raise ValueError('graph/request entry configuration mismatch')
        roots = {name: Path(request[field]).resolve() for name, field in
                 [('workspace', 'workspace'), ('dotnet', 'dotnetRoot'), ('packages', 'packageRoot')]}
        roots['adapter'] = ROOT / 'tools/GraphExport'
        if roots['dotnet'].is_relative_to('/nix/store'):
            roots['nix'] = Path('/nix/store')
        records, owners = {}, {}
        groups = [(None, graph['graphInputs'])] + [(node['id'], node['inputs']) for node in graph['nodes']]
        for owner, inputs in groups:
            for item in inputs:
                if item['kind'] not in ('project', 'import'):
                    continue
                logical = item['path']
                key = (item['kind'], logical)
                prior = records.get(key)
                if prior is not None and prior != item:
                    raise ValueError('conflicting graph XML record: ' + logical)
                records[key] = item
                owners.setdefault(logical, set()).add(owner or '$graph')
        if not records or not graph['nodes']:
            raise ValueError('graph XML inventory is empty')
        contents, inventory, source_owners = {}, [], {}
        for (_, logical), item in sorted(records.items()):
            parts = PurePosixPath(logical).parts
            if len(parts) < 2 or parts[0] not in roots or any(p in ('.', '..') for p in logical.split('/')) or any(c in logical for c in ('\\', '\n', '\r', ':')) or '//' in logical:
                raise ValueError('unsafe graph XML path: ' + logical)
            path = roots[parts[0]].joinpath(*parts[1:])
            resolved = path.resolve()
            # SDK/Nix symlinks may cross stores, never escape the declared SDK/store domain.
            allowed = [roots[parts[0]]]
            if parts[0] in ('dotnet', 'nix') and 'nix' in roots:
                allowed.append(roots['nix'])
            if not path.is_file() or not any(resolved.is_relative_to(root) for root in allowed):
                raise ValueError('missing or escaping graph XML input: ' + logical)
            raw = path.read_bytes()
            fingerprint = raw
            if item['kind'] == 'import' and path.suffix.lower() in TEXT_IMPORTS:
                value = import_text(raw)
                for name, token in [('workspace', '$WORKSPACE'), ('packages', '$PACKAGES'), ('dotnet', '$DOTNET')]:
                    value = value.replace(str(roots[name]), token)
                fingerprint = value.encode('utf-8')
            if hashlib.sha256(fingerprint).hexdigest() != item['sha256']:
                raise ValueError('stale graph XML input: ' + logical)
            if resolved in contents and contents[resolved] != raw:
                raise ValueError('graph XML changed during inventory: ' + logical)
            contents[resolved] = raw
            source_owners.setdefault(str(resolved), set()).update(owners[logical])
            inventory.append(dict(path=logical, kind=item['kind'], sha256=item['sha256'],
                configuredNodes=sorted(owners[logical])))
        # Scan the exact verified bytes once; do not follow inactive literal imports
        # or re-read files after verification.
        report.update(scan(sorted(contents), follow_imports=False, contents=contents))
        report.update(scope='msbuild-evaluated-import-time-diagnostics', inventoryVerified=True,
            inventory=inventory, entryRequests=graph.get('entryRequests', []),
            configurations=[dict(id=n['id'], project=n['project'], globalProperties=n['globalProperties']) for n in graph['nodes']])
        for gap in report['coverageGaps']:
            if gap['reason'].startswith('implicit SDK imports'):
                gap['reason'] = 'SDK import files come from the exported snapshot; SDK resolution is not re-run'
        for finding in report['findings']:
            finding['configuredNodes'] = sorted(source_owners[finding['file']])
        report['coverageGaps'].extend([
            dict(reason='snapshot membership only: re-export to observe new globs, optional imports, references or changed configuration'),
            dict(reason='export omits generated NuGet import wrappers; resolved package imports are inventoried separately'),
            dict(reason='XML conditions are not executed by the scanner; configured ownership does not prove a finding ran'),
            dict(reason='environment, task/process reads, filesystem timestamps and undeclared external reads are not enforced')])
    except (OSError, ValueError, KeyError, TypeError) as error:
        report['errors'].append(dict(file=str(request_path), message=str(error)))
    return report
