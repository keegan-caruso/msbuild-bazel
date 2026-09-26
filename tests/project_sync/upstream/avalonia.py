"""Map the pinned, authored Avalonia graph to production ProjectSync contracts.

The first pass retains authored tool producers for evaluation bootstrap. After
synchronizing, --generated replaces all project declarations with generated aliases.
"""
import argparse
import ast
import base64
import hashlib
import shutil
from collections import defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from defaults import compact
# Do not let the sibling qualification driver http.py shadow the standard library.
sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "explicit_msbuild/avalonia"))
from suite_support import selections

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('prepared', type=Path)
p.add_argument('workspace', type=Path)
p.add_argument('--generated', action='store_true')
a = p.parse_args(); prepared = a.prepared.resolve(); w = a.workspace.resolve()
rules = Path(__file__).resolve().parents[3]
records = {}
for line in (prepared / 'bazel/upstream/BUILD.bazel').read_text().splitlines():
    if not line or line.startswith('load('): continue
    node = ast.parse(line).body[0].value
    attrs = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
    for key in ['project','archive']:
        if key in attrs: attrs[key] = 'upstream/' + attrs[key]
    for key in ['srcs','msbuild_imports','adapter_imports']:
        if key in attrs: attrs[key] = [value if value.startswith((':','@','//')) else 'upstream/' + value for value in attrs[key]]
    records[attrs['name']] = (node.func.id, attrs)
projects = {(v['project'], v['target_framework']): v for kind,v in records.values() if kind in ['msbuild_library','msbuild_binary']}
assert len(projects) == 53 and len({p for p,f in projects}) == 40
rows = {('upstream/'+r['project'],r['framework']):r for r in json.loads((prepared/'evaluation.json').read_text())}
assert all(key in rows and 'error' not in rows[key] for key in projects)
reviewed = json.loads(Path(__file__).with_name('avalonia-contracts.json').read_text())
config = json.loads((prepared/'config.json').read_text())
inventory = json.loads((prepared/'inventory.json').read_text())
node_ids = {('upstream/'+r['project'],r['framework']):r['id'] for r in inventory}
labels = json.loads((prepared/'labels.json').read_text())
inputs = {':' + r['label']: 'upstream/'+r['output'] for r in json.loads((prepared/'expanded-generators.json').read_text())}

def call(rule, **attrs):
    return rule + '(' + ','.join(k + '=' + repr(v) for k,v in attrs.items()) + ')'

def name(project, framework):
    return project.removesuffix('.csproj').replace('/','_') + '_' + framework.replace('.','_')

lines = ['load("@rules_msbuild//msbuild:defs.bzl", "msbuild_library", "msbuild_binary", "msbuild_nuget_package", "msbuild_nuget_dependencies", "msbuild_package_lock", "msbuild_items", "msbuild_tool", "msbuild_file_binding", "msbuild_generate", "msbuild_test_tool")', 'load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")']
for kind, attrs in records.values():
    if kind in ['msbuild_toolchain','toolchain'] or attrs['name'] == 'benchmark': continue
    attrs = dict(attrs); attrs.pop('allow_remote_execution',None)
    if kind in ['msbuild_library','msbuild_binary'] and a.generated:
        lines.append(call('alias',name=attrs['name'],actual=':'+name(attrs['project'],attrs['target_framework'])))
    else:
        lines.append(call(kind,**attrs))

mapping = dict(projects={},packages={},tests={})
variants = defaultdict(dict)
for key, previous in projects.items():
    project, framework = key; row = rows[key]
    binding = dict(packageLock=previous['package_lock'], packages={}, projectReferences={}, references={}, documents={},
                   linuxWorker=True, profileBuild=True, properties={'AvsSkipBuildingLegacyTargetFrameworks':'True'},
                   tools=previous['tools'],bindings=previous['bindings'],adapterImports=[p if p.startswith((':','@','//')) else ':'+p for p in previous.get('adapter_imports',[])],
                   inputItems={'AvaloniaResource':[], 'AvaloniaXaml':[], 'AdditionalFiles':['SourceItemGroup','DBusGeneratorMode']},
                   evaluationItems=['AssemblyAttribute','CompilerVisibleProperty','CompilerVisibleItemMetadata','AvailableItemName','PropertyPageSchema','Service','SupportedPlatform','MicroComIdl'])
    binding['assemblySelections'] = selections(inventory, node_ids[key], labels)
    evaluated_files = {(item['type'], 'upstream/' + (prepared/'source'/Path(project.removeprefix('upstream/')).parent/item['include'].replace('\\','/')).resolve().relative_to(prepared/'source').as_posix()) for item in row['items'] if item['type'] == 'AdditionalFiles'}
    # Package targets are intentionally not executed during local synchronization.
    # Preserve their reviewed file inputs as explicit item bindings.
    binding['items'] = [label for label in previous['items'] if records[label[1:]][1]['item_type'] == 'AdditionalFiles' and any(('AdditionalFiles', path) not in evaluated_files for path in records[label[1:]][1]['srcs'])]

    # MicroCom input paths are declared by the five explicit generation actions.
    # Its SDK generation targets are replaced only by the qualified consumer adapter.
    for doc in row['documents']:
        if not (doc['targets'] or doc['tasks']): continue
        observed = {k:doc[k] for k in ['sha256','targets','tasks']}
        assert reviewed.get(doc['path']) == observed, ('Unreviewed document',doc['path'])
        binding['documents']['upstream/'+doc['path']] = observed
    for item in row['items']:
        identity = item['include']
        if item['type'] == 'ProjectReference':
            child = 'upstream/' + (prepared/'source'/Path(project.removeprefix('upstream/')).parent/identity.replace('\\','/')).resolve().relative_to(prepared/'source').as_posix()
            candidates = []
            for role, attribute in [('compile','deps'),('private','implementation_deps'),('analyzer','analyzers'),('tool','tools')]:
                for label in previous[attribute]:
                    producer = records[label[1:]][1]
                    if role == 'tool': producer = records[producer['assembly'][1:]][1]
                    if producer.get('project') == child: candidates.append(dict(role=role,label=label))
            assert len(candidates) == 1, (project,child,candidates)
            binding['projectReferences'][child] = candidates[0]
        elif item['type'] == 'Reference':
            binding['references'][identity] = dict(role='framework')
    for package in row['packages']:
        matches = []
        for label in previous['deps']:
            kind, attrs = records[label[1:]]
            if kind != 'msbuild_nuget_dependencies': continue
            archive = records[attrs['package'][1:]][1]
            if archive['package_id'].lower() == package['id'].lower(): matches.append((label,archive))
        assert len(matches) == 1, (key,package,matches)
        label, archive = matches[0]
        version = package['versionOverride'] or package['version'] or archive['version']
        binding['packages'][package['id']+'/'+version] = dict(label=label,roles=['deps','build_deps','analyzers'])
    variants[project][framework] = binding
for project, frameworks in variants.items():
    mapping['projects'][project] = dict(targetFrameworks=sorted(frameworks),properties={'AvsSkipBuildingLegacyTargetFrameworks':'True'},frameworkOverrides=frameworks)
test_inputs = json.loads((prepared/'test-inputs.json').read_text()) if (prepared/'test-inputs.json').exists() else None
if a.generated: assert test_inputs, 'Prepare pinned native/test tools first'
if test_inputs:
    archive = Path(test_inputs['archive']); data = archive.read_bytes()
    assert hashlib.sha256(data).hexdigest() == test_inputs['digest']
    shutil.copyfile(archive,w/'upstream/locked-packages'/archive.name)
    lines += [call('msbuild_nuget_package',name='expanded_runner_package',package_id='Microsoft.TestPlatform.CLI',version='17.14.1',archive='upstream/locked-packages/'+archive.name,archive_sha256=test_inputs['digest'],content_hash=base64.b64encode(hashlib.sha512(data).digest()).decode()),
              call('msbuild_test_tool',name='expanded_runner',package=':expanded_runner_package',path='contentFiles/any/net9.0/vstest.console.dll'),
              call('msbuild_test_tool',name='expanded_adapter',package=':archive_xunit.runner.visualstudio_2.8.2',path='build/net6.0')]
    (w/'upstream/native-tests').mkdir(exist_ok=True)
    shutil.copyfile(prepared/'bazel/upstream/native-tests/fonts.conf',w/'upstream/native-tests/fonts.conf')
    for filename in ['native-packages.json','native_packages.bzl']:
        shutil.copyfile(prepared/'bazel'/filename,w/filename)

for entry in config['entries']:
    project = 'upstream/' + entry
    if '/tests/' in '/' + project:
        mapping['tests'][project] = dict(protocol='vstest',outputType=next(r['properties']['OutputType'].lower() for r in inventory if r['project']==entry and r['entry']),runner=':expanded_runner',adapters=[':expanded_adapter'],properties={},environment={'DOTNET_ROLL_FORWARD':'Major'})
        for variant in variants[project].values():
            variant['runtimeHost']='@dotnet//:sdk_host'
            # Restored Test SDK evaluation changes OutputType after the SDK's
            # apphost default was computed for the authored Library setting.
            variant['useAppHost']=False
        if test_inputs and '/Avalonia.Skia.' in project:
            test = mapping['tests'][project]
            test['workingDirectory'] = 'tests'
            test['dataPaths'] = {key if key.startswith('@') else 'upstream/'+key:value for key,value in test_inputs['data'].items()}
            test['environment'].update(LD_LIBRARY_PATH='native-tests',FONTCONFIG_PATH='native-tests',FONTCONFIG_FILE='fonts.conf')
            if '/Avalonia.Skia.RenderTests/' in project:
                test['dataPaths'].update({f.relative_to(w).as_posix():f.relative_to(w/'upstream').as_posix() for f in (w/'upstream/tests/TestFiles').rglob('*') if f.is_file() and not f.name.endswith('.out.png')})
lines.append(call('msbuild_sync',name='sync',projects=sorted(variants),mappings='sync.json',inputs=inputs,
                  package_locks=sorted({v['package_lock'] for v in projects.values()}),
                  bindings=sorted({label for v in projects.values() for label in v['bindings']})))
(w/'BUILD.bazel').write_text(('load(":projects.generated.bzl", "app_projects")\n' if a.generated else '')+'\n'.join(lines)+'\n'+('app_projects()\n' if a.generated else ''))
(w/'sync.json').write_text(json.dumps(compact(mapping),indent=2)+'\n')
(w/'MODULE.bazel').write_text('module(name="avalonia_sync")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(rules))+')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",version="10.0.400")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
if test_inputs:
    module = w/'MODULE.bazel'
    module.write_text(module.read_text()+'native_runtime = use_repo_rule("//:native_packages.bzl", "native_runtime")\nnative_runtime(name="avalonia_native",lock="//:native-packages.json",include_vnc=True)\n')
(w/'.bazelversion').write_text((rules/'.bazelversion').read_text())
print('mapped',len(projects),'configured nodes',len(variants),'projects',flush=True)
