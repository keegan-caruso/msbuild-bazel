"""Migrate Http.Abstractions and its tests; retain explicit dependency producers.

Inputs: authored ASP.NET workspace, evaluation inventory, prepared ObjectPool
workspace (for its already-qualified bootstrap and test tooling). No generated
ProjectSync output is edited. All custom contracts reuse the reviewed ASP.NET set.
"""
import ast
import json
from pathlib import Path
import shutil
import sys

outer, inventory, bootstrap = map(lambda p: Path(p).resolve(), sys.argv[1:])
root = outer / 'upstream'
rules = Path(__file__).resolve().parents[3]
rows = json.loads(inventory.read_text())
assert all(r.get('framework') == 'net10.0' for r in rows), rows
reviewed = json.loads(Path(__file__).with_name('objectpool-contracts.json').read_text())
bootstrap_mapping = json.loads((bootstrap / 'sync.json').read_text())
bookkeeping = next(iter(bootstrap_mapping['projects'].values()))['evaluationItems']

def call(rule, **attrs):
    return rule + '(' + ','.join(k + '=' + (str(v) if isinstance(v, bool) else json.dumps(v)) for k, v in attrs.items()) + ')'

def records(path):
    result = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith('load('): continue
        node = ast.parse(line).body[0].value
        attrs = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
        result[attrs['name']] = (node.func.id, attrs)
    return result

old = records(root / 'BUILD.bazel')
extras = records(bootstrap / 'BUILD.bazel')
def qualify(value):
    if isinstance(value, str): return ':bootstrap_' + value[1:] if value.startswith(':') else value
    if isinstance(value, list): return [qualify(v) for v in value]
    if isinstance(value, dict): return {qualify(k): qualify(v) for k, v in value.items()}
    return value

extras = {name: (rule, dict(qualify(attrs), name='bootstrap_' + name)) for name, (rule, attrs) in extras.items()}
inputs = extras['sync'][1]['inputs']
projects = {row['project'] for row in rows}
selected = {attrs['project']: attrs for rule, attrs in old.values() if attrs.get('project') in projects}
assert len(selected) == 2
shutil.copytree(bootstrap / 'locked-packages', root / 'locked-packages', dirs_exist_ok=True)
shutil.copyfile(bootstrap / 'bootstrap.targets', root / 'bootstrap.targets')
shutil.copyfile(bootstrap / 'layout.targets', root / 'layout.targets')
# Replace captured bootstrap files with the declared generation action everywhere.
for path in inputs.values(): (root / path).unlink(missing_ok=True)
lines = ['load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_binary","msbuild_nuget_package","msbuild_nuget_dependencies","msbuild_package_lock","msbuild_items","msbuild_tool","msbuild_project_output","msbuild_generate","msbuild_test_tool")', 'load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")']
for name, (rule, attrs) in extras.items():
    if name in ['sync', 'vstest', 'xunit', 'vstest_package']: continue
    assert attrs['name'] not in old, name
    lines.append(call(rule, **attrs))
for name, (rule, attrs) in old.items():
    if rule in ['msbuild_toolchain', 'toolchain'] or name == 'benchmark': continue
    assert rule != 'unsupported_project', attrs
    if attrs.get('project') in projects:
        generated = attrs['project'].removesuffix('.csproj').replace('/', '_') + '_net10_0'
        lines.append(call('alias', name=name, actual=':' + generated))
        continue
    if rule in ['msbuild_library', 'msbuild_binary']:
        attrs['msbuild_properties'].pop('WarningsNotAsErrors', None)
        attrs['msbuild_imports'] = [p for p in attrs['msbuild_imports'] if p not in inputs.values()]
        attrs['import_paths'] = inputs
        attrs['directories'] = [p.removeprefix('upstream/') for p in attrs['directories']]
    # Copied NuGet.config is test data, not the restore configuration.
    if rule == 'msbuild_items' and attrs.get('srcs') == ['NuGet.config']:
        attrs.pop('srcs'); attrs['paths'] = {':NuGet.config': 'qualification-data/NuGet.config'}
    lines.append(call(rule, **attrs))
mapping = {'projects': {}, 'packages': {}, 'tests': {}}
# Restore evaluates dependency project records, including private package edges.
locked = {label for rule, attrs in old.values() if rule == 'msbuild_package_lock' for label in attrs['packages']}
for row in rows:
    project = row['project']; previous = selected[project]
    locked.update(old[previous['package_lock'][1:]][1]['packages'])
    binding = dict(targetFrameworks=['net10.0'], properties={k: v for k, v in previous['msbuild_properties'].items() if k != 'WarningsNotAsErrors'}, adapterImports=[':layout.targets'], directories=['artifacts/installers/Release','artifacts/VSSetup/Release'], documents={}, references={}, projectReferences={}, evaluationItems=bookkeeping)
    for doc in row['documents']:
        if not (doc['targets'] or doc['tasks']): continue
        contract = {k: doc[k] for k in ['sha256', 'targets', 'tasks']}
        key = doc['path'].lower() if doc['path'].startswith('.nuget/') else doc['path']
        assert reviewed.get(key) == contract, ('Unreviewed custom document', doc['path'])
        binding['documents'][doc['path']] = contract
    binding['documents']['Directory.Build.targets']['inputs'] = [p for p in previous['msbuild_imports'] if p not in inputs.values()]
    binding['documents']['Directory.Build.targets']['inputs'] += [p.relative_to(root).as_posix() for p in (root / Path(project).parent).glob('PublicAPI*.txt')]
    for ref in row['items']:
        identity = ref['include']
        if ref['type'] == 'ProjectReference':
            source = next(p for p in Path(row['assets']).parents if p.name == 'artifacts').parent
            path = (source / Path(project).parent / identity.replace('\\', '/')).resolve().relative_to(source).as_posix()
            candidates = [d for d in previous['deps'] if old[d[1:]][1].get('project') == path]
            assert len(candidates) == 1, (identity, candidates)
            path = old[candidates[0][1:]][1]['project']
            binding['projectReferences'][path] = dict(role='compile', label=candidates[0])
        if ref['type'] not in ['Reference', 'PackageReference']: continue
        candidates = []
        for label in previous['deps'] + previous['reference_packages']:
            rule, attrs = old[label[1:]]
            if rule != 'msbuild_nuget_dependencies': continue
            package = old[attrs['package'][1:]][1]
            if package['package_id'].lower() == identity.lower(): candidates.append((label, package))
        assert len(candidates) <= 1, (identity, candidates)
        if ref['type'] == 'Reference':
            binding['references'][identity] = dict(role='package', label=candidates[0][0], roles=['build_deps','analyzers']) if candidates else dict(role='framework')
        else:
            assert candidates, identity
            label, package = candidates[0]
            mapping['packages'][identity + '/' + package['version']] = dict(label=label, roles=['deps','build_deps','analyzers'])
    if '/test/' in project:
        binding['runtimeHost'] = '@dotnet//:sdk_host'
        binding['itemPaths'] = {'NuGet.config': 'qualification-data/NuGet.config'}
        mapping['tests'][project] = dict(protocol='vstest', runner=':bootstrap_vstest', adapters=[':bootstrap_xunit'], outputDirectories=['test-logs'])
    mapping['projects'][project] = binding
for name in ['vstest_package', 'vstest', 'xunit']: lines.append(call(extras[name][0], **extras[name][1]))
lines.append(call('msbuild_package_lock', name='sync_packages', packages=sorted(locked)))
lines.append(call('msbuild_sync', name='sync', projects=sorted(projects), mappings='sync.json', inputs=inputs, package_lock=':sync_packages'))
(root / 'BUILD.bazel').write_text('\n'.join(lines) + '\n')
(root / 'sync.json').write_text(json.dumps(mapping, indent=2) + '\n')
shutil.copyfile(bootstrap / 'MODULE.bazel', root / 'MODULE.bazel')
shutil.copyfile(rules / '.bazelversion', root / '.bazelversion')
print(root)
