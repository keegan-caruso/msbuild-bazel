"""Declare unchanged Add1_ro and its authored bootstrap on a qualified runtime graph.

The supplied raw workspace must have built external, test_dependencies and Add1_ro
with the pinned source/packages. Only authored files are copied; all generated
inputs come from Bazel producer targets. Large runtime/native producers are reused.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
ENTRY = 'src/tests/JIT/CodeGenBringUpTests/Add1_ro.csproj'
CODE = 'src/tests/JIT/CodeGenBringUpTests/Add1.cs'
WRAPPER = 'src/tests/Common/XUnitWrapperGenerator/XUnitWrapperGenerator.csproj'
EXTERNAL = 'src/tests/Common/external/external.csproj'
DEPENDENCIES = 'src/tests/Common/test_dependencies/test_dependencies.csproj'
ASSETS = 'artifacts/tests/coreclr/packages/Common/test_dependencies/test_dependencies'
REFS = 'artifacts/bin/ref/net10.0'
TEST_OUTPUT = 'artifacts/tests/coreclr/linux.arm64.Release/JIT/CodeGenBringUpTests/Add1_ro'
PINNED = {ENTRY: '511e72cd4b9d3b2842e390c9640eb3f55b7a385027b000ea08f80fddc33062af',
          CODE: '830fce95a0aac6a98209f9e4edb365801a50badbd55ddded0a103814fca2e158'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path, help='qualified 481-node source runtime workspace')
    parser.add_argument('raw', type=Path, help='successful authored JIT bootstrap workspace')
    args = parser.parse_args()
    root, raw = args.workspace.resolve(), args.raw.resolve()
    assert root != raw and not (root / 'jit.json').exists()
    application = json.loads((root / 'application.json').read_text())
    assert application['commit'] == '60629d14374c56f1cb51819049ad1fa529307f8d'
    for path, digest in PINNED.items():
        assert hashlib.sha256((raw / path).read_bytes()).hexdigest() == digest, 'Authored JIT source changed: ' + path
    assert (raw / TEST_OUTPUT / 'Add1_ro.dll').is_file(), 'Raw unchanged test must compile first'
    authored = [p for path in ['eng', 'src/tests/Common', 'src/tests/JIT/CodeGenBringUpTests']
                for p in (raw / path).rglob('*') if p.is_file()]
    authored += [raw / p for p in ['global.json', 'Directory.Build.props', 'Directory.Build.targets',
                 'NuGet.Config', 'src/tests/Directory.Build.props', 'src/tests/Directory.Build.targets',
                 'src/tests/Directory.Merged.props', 'src/tests/JIT/Directory.Build.props',
                 'src/coreclr/Directory.Build.props', 'src/coreclr/Directory.Build.targets', 'src/coreclr/clr.featuredefines.props']]
    paths = sorted({str(p.relative_to(raw)) for p in authored})
    for path in paths:
        destination = root / path
        if destination.exists():
            assert destination.read_bytes() == (raw / path).read_bytes(), 'Existing authored input changed: ' + path
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(raw / path, destination)
    shared = [p for p in paths if not p.endswith(('.cs', '.csproj'))]
    properties = dict(Configuration='Release', TargetOS='linux', TargetArchitecture='arm64',
                      BuildAllTestsAsStandalone='true', CLRTestPriorityToBuild='1', NuGetAudit='false',
                      LibrariesSharedFrameworkRefArtifactsPath='/__rules_msbuild_graph/output/workspace/' + REFS + '/')
    def declaration(project):
        relative = str(Path(project).parent.relative_to('src/tests')) + '/' + Path(project).stem
        return dict(Inputs=[project], OutputDirectories=[
            'artifacts/tests/coreclr/linux.arm64.Release/' + relative,
            'artifacts/tests/coreclr/obj/linux.arm64.Release/Managed/' + relative])
    def contract(entries, projects, extra=()):
        return dict(Version=6, Entry=entries[0], Entries=entries, SdkVersion='10.0.400',
                    Properties=properties, SharedInputs=shared + list(extra), Projects=projects,
                    DefinitionDigests={p: hashlib.sha256((root / p).read_bytes()).hexdigest()
                                       for p in shared + list(projects)})
    bootstrap = contract([EXTERNAL, DEPENDENCIES], {
        EXTERNAL: dict(Inputs=[EXTERNAL], OutputDirectories=['artifacts/TargetingPack',
            'artifacts/tests/coreclr/obj/linux.arm64.Release/Managed/Common/external/external']),
        DEPENDENCIES: declaration(DEPENDENCIES)})
    # The authored external project deploys packages and intentionally emits no
    # assembly. TargetPath="" marks that generic artifact-only cache boundary.
    bootstrap['EntryProperties'] = {EXTERNAL: {'TargetPath': ''}}
    outputs = []
    for project in [EXTERNAL, DEPENDENCIES]:
        directory = 'artifacts/tests/coreclr/packages/' + str(Path(project).parent.relative_to('src/tests')) + '/' + Path(project).stem
        outputs += [directory + '/' + name for name in ['project.assets.json', 'project.nuget.cache',
            Path(project).name + '.nuget.dgspec.json', Path(project).name + '.nuget.g.props', Path(project).name + '.nuget.g.targets']]
    bootstrap['Restore'] = dict(Inputs=shared + [EXTERNAL, DEPENDENCIES], Outputs=outputs)
    def products(directory):
        found = sorted(str(p.relative_to(raw)) for p in (raw / directory).rglob('*') if p.is_file())
        assert found, 'Missing raw producer inventory: ' + directory
        return found
    generated = products('artifacts/TargetingPack') + products(ASSETS) + products(REFS)
    test = declaration(ENTRY)
    test['Inputs'] += [CODE]
    wrapper = declaration(WRAPPER)
    wrapper['Inputs'] += [p for p in paths if p.startswith(str(Path(WRAPPER).parent) + '/') and p.endswith('.cs')]
    wrapper['Inputs'].append('src/tests/Common/XUnitWrapperLibrary/TestFilter.cs')
    test['ImplementationDependencies'] = [WRAPPER]
    graph = contract([DEPENDENCIES, ENTRY], {ENTRY: test, WRAPPER: wrapper, DEPENDENCIES: declaration(DEPENDENCIES)}, generated)
    graph['Entry'] = ENTRY
    (root / 'jit-bootstrap.json').write_text(json.dumps(bootstrap, indent=2) + '\n')
    (root / 'jit-test.json').write_text(json.dumps(graph, indent=2) + '\n')
    feed = json.loads(Path(__file__).with_name('runtime_jit_packages.json').read_text())
    for key, record in feed.items():
        identity, version = key.split('/')
        name = identity + '.' + version + '.nupkg'
        source = raw / '.package-source' / name
        data = source.read_bytes()
        assert hashlib.sha256(data).hexdigest() == record['sha256'], 'JIT package changed: ' + key
        shutil.copyfile(source, root / '.package-source' / name)
    # Reuse the reviewed offline feed, including Arcade and framework baselines.
    lines = ['load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph", "msbuild_graph_restore", "msbuild_graph_output", "msbuild_graph_test", "msbuild_layout", "msbuild_runtime")']
    archives = sorted(str(p.relative_to(root)) for p in (root / '.package-source').glob('*.nupkg'))
    attributes = dict(runner=':graph_runner', contract='jit-bootstrap.json', srcs=shared + [EXTERNAL, DEPENDENCIES],
                      packages=archives, linux_stable_paths=True)
    def rule(kind, **kwargs):
        return kind + '(' + ','.join(k + '=' + repr(v) for k, v in kwargs.items()) + ')'
    lines += [rule('msbuild_graph_restore', name='jit_bootstrap_restore', **attributes),
              rule('msbuild_graph', name='jit_bootstrap', restore=':jit_bootstrap_restore', linux_worker=True, **attributes),
              rule('msbuild_graph_output', name='jit_targeting_pack', graph=':jit_bootstrap', path='artifacts/TargetingPack', directory=True),
              rule('msbuild_graph_output', name='jit_assets', graph=':jit_bootstrap_restore', path=ASSETS, directory=True),
              rule('msbuild_graph_output', name='jit_refs', graph=':graph', path=REFS, directory=True),
              rule('msbuild_graph', name='jit_test_build', runner=':graph_runner', contract='jit-test.json',
                   srcs=sorted(set(shared + test['Inputs'] + wrapper['Inputs'] + [DEPENDENCIES])), packages=archives,
                   input_paths={':jit_targeting_pack': 'artifacts/TargetingPack', ':jit_assets': ASSETS, ':jit_refs': REFS},
                   linux_stable_paths=True, linux_worker=True)]
    # Assemble corerun's flat CORE_ROOT from the declared source-built framework,
    # authored external package deployment and pinned native producer outputs.
    host = {}
    for index, (name, product) in enumerate(sorted(application['managed'].items())):
        label = 'jit_framework_' + str(index)
        lines.append(rule('msbuild_graph_output', name=label, graph=':graph', path=product['path']))
        host[':' + label] = name
    host.update({row['label']: name for name, row in application['native'].items() if name.endswith('.so')})
    host.update({':jit_targeting_pack': '.', '//native:host': 'corerun'})
    lines += [rule('msbuild_layout', name='jit_core_root', paths=host),
              rule('msbuild_runtime', name='jit_host', layout=':jit_core_root', entry_point='corerun', launch_mode='corerun',
                   runtime_identifier='linux-arm64', version='10.0.0'),
              rule('msbuild_graph_test', name='jit_add1', graph=':jit_test_build', assembly=TEST_OUTPUT + '/Add1_ro.dll',
                   runtime_host=':jit_host', expected_exit_code=100)]
    with (root / 'BUILD.bazel').open('a') as build:
        build.write('\n' + '\n'.join(lines) + '\n')
    summary = dict(commit=application['commit'], sourceDigests=PINNED, entry=ENTRY, properties=properties,
                   bootstrapEntries=[EXTERNAL, DEPENDENCIES], generatedInputs=len(generated), authoredInputs=len(paths),
                   additionalPackages=len(feed), test='//:jit_add1', sourceHost='jit_core_root.layout')
    (root / 'jit.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(root, flush=True)


if __name__ == '__main__':
    main()
