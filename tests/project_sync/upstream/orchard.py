"""Replace the qualified Orchard compilation graph with production synchronization.

Run after full_graph.py on a disposable restored source and copy its input tree
without bin/obj/.git to WORKSPACE. No generated declarations are edited.
"""
import ast
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from defaults import compact

workspace, inventory, source_root = [Path(p).resolve() for p in sys.argv[1:]]
rules = Path(__file__).resolve().parents[3]
rows = json.loads(inventory.read_text())
assert len(rows) == 202 and not any('error' in row for row in rows)
reviewed = json.loads(Path(__file__).with_name('orchard-contracts.json').read_text())
records = {}
for line in (workspace / 'BUILD.bazel').read_text().splitlines():
    if not line or line.startswith('load('): continue
    node = ast.parse(line).body[0].value
    attrs = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
    records[attrs['name']] = (node.func.id, attrs)
projects = {attrs['project']: attrs for kind, attrs in records.values() if kind in ['msbuild_library', 'msbuild_binary']}
assert set(projects) == {r['project'] for r in rows}
def call(kind, **attrs):
    return kind + '(' + ','.join(key + '=' + (str(value) if isinstance(value, bool) else json.dumps(value)) for key, value in attrs.items()) + ')'
def generated(project, attrs):
    name = project.removesuffix('.csproj').replace('/', '_')
    return name if records[attrs['name']][0] == 'msbuild_binary' else name + '_' + attrs['target_framework'].replace('.', '_')
lines = ['load("@rules_msbuild//msbuild:defs.bzl","msbuild_nuget_package","msbuild_nuget_dependencies","msbuild_package_lock","msbuild_target_items","msbuild_items")', 'load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")']
archives = []
for kind, attrs in records.values():
    if kind in ['msbuild_nuget_package', 'msbuild_nuget_dependencies', 'msbuild_target_items', 'msbuild_package_lock']:
        lines.append(call(kind, **attrs))
    if kind == 'msbuild_nuget_package': archives.append(':' + attrs['name'])
for project, attrs in projects.items():
    lines.append(call('alias', name=attrs['name'], actual=':' + generated(project, attrs)))
styles = sorted({path for attrs in projects.values() for path in attrs['msbuild_imports'] if path.endswith('.editorconfig')})
style_labels = {}
for index, path in enumerate(styles):
    label = '_sync_compiler_policy_' + str(index)
    lines.append(call('msbuild_items', name=label, item_type='None', srcs=[path]))
    style_labels[path] = ':' + label
mapping = dict(projects={}, packages={})
for row in rows:
    project = row['project']; previous = projects[project]
    binding = dict(packages={}, packageLock=previous['package_lock'], targetFrameworks=[row['framework']], linuxWorker=True, profileBuild=True, documents={}, projectReferences={}, inputItems={'None': [], 'RazorGenerate': []}, evaluationItems=['GlobalPackageReference', 'Folder', 'Watch', 'AssemblyAttribute', 'TypeScriptCompile'], directories=previous['directories'])
    if project == 'src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj':
        binding['generatedDirectories'] = {'src/OrchardCore.Cms.Web/Localization': 'Localization'}
    if project.endswith('/OrchardCore.SourceGenerators.csproj'):
        # Pack-only output descriptors do not participate in this build slice.
        del binding['inputItems']['None']
    binding['items'] = [label for label in previous['items'] if records[label[1:]][0] == 'msbuild_target_items'] + [style_labels[path] for path in previous['msbuild_imports'] if path in style_labels]
    if 'export_targets' in previous: binding['exportTargets'] = previous['export_targets']
    for document in row['documents']:
        if not (document['targets'] or document['tasks']): continue
        observed = {k: document[k] for k in ['sha256', 'targets', 'tasks']}
        assert reviewed.get(document['path']) == observed, ('Unreviewed custom document', document['path'])
        binding['documents'][document['path']] = observed
    for item in row['items']:
        if item['type'] != 'ProjectReference': continue
        child = (source_root / Path(project).parent / item['include'].replace('\\', '/')).resolve().relative_to(source_root).as_posix()
        metadata = item['metadata']
        role = 'analyzer' if metadata.get('OutputItemType') == 'Analyzer' else 'private' if metadata.get('PrivateAssets', '').lower() == 'all' else 'compile'
        binding['projectReferences'][child] = dict(role=role, label=':' + projects[child]['name'])
    for package in row['packages']:
        labels = []
        for label in previous['deps']:
            kind, attrs = records[label[1:]]
            if kind != 'msbuild_nuget_dependencies': continue
            archive = records[attrs['package'][1:]][1]
            if archive['package_id'].lower() == package['id'].lower(): labels.append((label, archive))
        assert len(labels) == 1, (project, package, labels)
        label, archive = labels[0]
        binding['packages'][package['id'] + '/' + (package['versionOverride'] or package['version'] or archive['version'])] = dict(label=label, roles=['deps', 'build_deps', 'analyzers'])
    mapping['projects'][project] = binding
lines.append(call('msbuild_sync', name='sync', projects=sorted(projects), mappings='sync.json', package_locks=sorted({p['package_lock'] for p in projects.values()})))
(workspace / 'BUILD.bazel').write_text('\n'.join(lines) + '\n')
(workspace / 'sync.json').write_text(json.dumps(compact(mapping), indent=2) + '\n')
(workspace / 'MODULE.bazel').write_text('module(name="orchard_sync")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path=' + json.dumps(str(rules)) + ')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",version="10.0.400")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
(workspace / '.bazelversion').write_text((rules / '.bazelversion').read_text())
# Keep an independently authored graph description for later edge comparison.
(workspace.parent / 'authored-projects.json').write_text(json.dumps(projects, indent=2) + '\n')
print('mapped', len(projects), 'projects', len(archives), 'archives', flush=True)
