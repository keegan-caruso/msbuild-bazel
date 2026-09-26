"""Generate the complete selected Http.Abstractions graph through ProjectSync.

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
assert all("error" not in r for r in rows), rows
reviewed = json.loads(Path(__file__).with_name('objectpool-contracts.json').read_text())
reviewed.update(json.loads(Path(__file__).with_name('http-contracts.json').read_text()))
bootstrap_mapping = json.loads((bootstrap / 'sync.json').read_text())
bookkeeping = next(iter(bootstrap_mapping['projects'].values()))['evaluationItems'] + ['BaselinePackageReference', '_InvalidReferenceToNonSharedFxAssembly', 'Components', 'InProcessComponents', 'RunInProcessComponents', 'RunShimComponents', 'ShimComponents', 'SupportedPlatform', 'UpToDateCheckInput']

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
if (outer / 'project-bindings.json').exists():
    old.update({name: (value['rule'], value['attributes']) for name, value in json.loads((outer / 'project-bindings.json').read_text()).items()})
extras = records(bootstrap / 'BUILD.bazel')
def qualify(value):
    if isinstance(value, str):
        if value.startswith(':'): return ':bootstrap_' + value[1:]
        if value.startswith('locked-packages/'): return 'bootstrap-packages/' + value.removeprefix('locked-packages/')
        return value
    if isinstance(value, list): return [qualify(v) for v in value]
    if isinstance(value, dict): return {qualify(k): qualify(v) for k, v in value.items()}
    return value

extras = {name: (rule, dict(qualify(attrs), name='bootstrap_' + name)) for name, (rule, attrs) in extras.items()}
inputs = extras['sync'][1]['inputs']
assemblies = [attrs for rule, attrs in old.values() if rule in ['msbuild_library', 'msbuild_binary']]
selected = {attrs['project']: attrs for attrs in assemblies}
assert len(selected) == len(assemblies) == 44, 'This slice requires 44 distinct configured project paths'
projects = set(selected)
rows = [row for row in rows if row['project'] in selected and row['framework'] == selected[row['project']]['target_framework']]
assert len(rows) == len(selected), (len(rows), len(selected))
shutil.copytree(bootstrap / 'locked-packages', root / 'bootstrap-packages', dirs_exist_ok=True)
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
        generated = attrs['project'].removesuffix('.csproj').replace('/', '_') + '_' + attrs['target_framework'].replace('.', '_')
        lines.append(call('alias', name=name, actual=':' + generated))
        continue
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
    binding = dict(targetFrameworks=[row['framework']], properties={k: v for k, v in previous['msbuild_properties'].items() if k != 'WarningsNotAsErrors'}, adapterImports=[':layout.targets'], directories=['artifacts/installers/Release','artifacts/VSSetup/Release'], documents={}, references={}, projectReferences={}, evaluationItems=bookkeeping)
    # None items can feed package generators (for example CsWin32 NativeMethods.txt)
    # even when they are not copied to the final output. Keep those task inputs explicit.
    binding['items'] = [label for label in previous['items'] if old[label[1:]][1]['item_type'] == 'None' and not any(k in old[label[1:]][1].get('metadata', {}) for k in ['CopyToOutputDirectory', 'CopyToPublishDirectory'])]
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
            candidates = []
            for role, attribute in [('compile', 'deps'), ('analyzer', 'analyzers'), ('tool', 'tools'), ('output', 'project_outputs')]:
                for label in previous[attribute]:
                    attrs = old[label[1:]][1]
                    producer = old[attrs['assembly'][1:]][1] if role in ['tool', 'output'] else attrs
                    if producer.get('project') == path:
                        candidates.append(dict(role=role, label=label))
            assert len(candidates) == 1, (identity, candidates)
            binding['projectReferences'][path] = candidates[0]
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
        if any(i['type'] in ['Content', 'None'] and i['include'].replace('\\', '/').endswith('NuGet.config') for i in row['items']):
            binding['itemPaths'] = {'NuGet.config': 'qualification-data/NuGet.config'}
        mapping['tests'][project] = dict(protocol='vstest', runner=':bootstrap_vstest', adapters=[':bootstrap_xunit'], outputDirectories=['test-logs'])
    mapping['projects'][project] = binding
mapping['packages']['NETStandard.Library/2.0.3'] = dict(label=':archive_netstandard.library_2.0.3', roles=['build_deps'])
for name in ['vstest_package', 'vstest', 'xunit']: lines.append(call(extras[name][0], **extras[name][1]))
lines.append(call('msbuild_package_lock', name='sync_packages', packages=sorted(locked)))
lines.append(call('msbuild_sync', name='sync', projects=sorted(projects), mappings='sync.json', inputs=inputs, package_lock=':sync_packages'))
(root / 'BUILD.bazel').write_text('\n'.join(lines) + '\n')
(root / 'sync.json').write_text(json.dumps(mapping, indent=2) + '\n')
shutil.copyfile(bootstrap / 'MODULE.bazel', root / 'MODULE.bazel')
shutil.copyfile(rules / '.bazelversion', root / '.bazelversion')
print(root)
