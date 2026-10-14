"""Export declared references and corerun from the qualified source-runtime graph.

Copy only authored/declared inputs into a relocatable producer module. Compilation
and native outputs remain Bazel edges; no products archive or producer report is
required. This is the pinned Linux ARM64 qualification, not full runtime bootstrap.
"""
import json
from pathlib import Path
import re
import shutil

from runtime_prepare import COMMIT


def same_input(first, second):
    if first.stat().st_size != second.stat().st_size or first.stat().st_mode & 0o777 != second.stat().st_mode & 0o777:
        return False
    with first.open('rb') as left, second.open('rb') as right:
        while True:
            block = left.read(1024 * 1024)
            if block != right.read(1024 * 1024):
                return False
            if not block:
                return True


def export_source_runtime(source, output, rules, resume=False):
    source, output = Path(source).resolve(), Path(output).resolve()
    assert (not output.exists() or resume and output.is_dir()) and not output.is_relative_to(source)
    application = json.loads((source / 'application.json').read_text())
    assert application['commit'] == COMMIT
    contract = json.loads((source / 'graph.generated.json').read_text())
    assert not contract.get('InputTrees'), 'This producer expects the qualified source-only runtime contract'
    wanted = {'graph.generated.bzl', 'graph.generated.json', 'nuget.lock.json', 'application.json'}
    wanted.update(contract['SharedInputs'])
    wanted.update(contract.get('DefinitionDigests', {}))
    wanted.update(contract.get('Restore', {}).get('Inputs', []))
    for project in contract['Projects'].values():
        wanted.update(project['Inputs'])
        for config in project.get('Configurations', []):
            wanted.update(config['Inputs'])
    for producer in {row['producer'] for row in application['native'].values()}:
        directory = source / producer
        assert directory.is_dir()
        # These are the declared inputs of the qualified native producer rules.
        # Acquisition reports and saved experimental archives are not inputs.
        native_inputs = ['BUILD.bazel', 'native_action.bzl', 'NativeBuild.cs', 'Task.csproj',
            'driver-contract.json', 'bwrap', 'source.tar', 'toolchain.tar']
        wanted.update(producer + '/' + name for name in native_inputs)
    for name in sorted(wanted):
        path = Path(name)
        assert not path.is_absolute() and '..' not in path.parts
        original = source / path
        assert original.is_file() and not original.is_symlink() and original.resolve().is_relative_to(source), name
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        assert not target.is_symlink()
        if target.exists():
            assert same_input(target, original), 'Changed producer input: ' + name
        else:
            shutil.copy2(original, target)
    module = (source / 'MODULE.bazel').read_text()
    module = re.sub(r'module\(name="[^"]+"\)', 'module(name="jit_source_runtime")', module)
    module = re.sub(r'local_path_override\(module_name="rules_msbuild",path="[^"]+"\)',
        'local_path_override(module_name="rules_msbuild",path=' + json.dumps(str(rules)) + ')', module)
    module = module.replace('dotnet.sdk(name="dotnet"', 'dotnet.sdk(name="jit_source_sdk"')
    module = module.replace('use_repo(dotnet,"dotnet")', 'use_repo(dotnet,dotnet="jit_source_sdk")')
    module = module.replace('nuget.lock(name="nuget"', 'nuget.lock(name="jit_source_nuget"')
    module = module.replace('use_repo(nuget,"nuget")', 'use_repo(nuget,nuget="jit_source_nuget")')
    module += 'bazel_dep(name="jit_bootstrap",version="0.0.0")\nlocal_path_override(module_name="jit_bootstrap",path="../bootstrap")\n'
    (output / 'MODULE.bazel').write_text(module)
    lines = ['load(":graph.generated.bzl","app_graph")',
        'load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph_output","msbuild_layout","msbuild_runtime")',
        'app_graph(name="graph",linux_stable_paths=True,linux_worker=True,evaluation_cache_mb=1024)',
        'msbuild_graph_output(name="references",graph=":graph",path="artifacts/bin/ref/net10.0",directory=True,visibility=["//visibility:public"])']
    paths = {'@jit_bootstrap//:targeting': '.', '//native:host': 'corerun'}
    for index, (name, product) in enumerate(sorted(application['managed'].items())):
        label = 'framework_' + str(index)
        lines.append('msbuild_graph_output(name=' + repr(label) + ',graph=":graph",path=' + repr(product['path']) + ')')
        paths[':' + label] = name
    paths.update({row['label']: name for name, row in application['native'].items() if name.endswith('.so')})
    lines += ['msbuild_layout(name="core_root",paths=' + repr(paths) + ',visibility=["//visibility:public"])',
        'msbuild_runtime(name="host",layout=":core_root",entry_point="corerun",launch_mode="corerun",runtime_identifier="linux-arm64",version="10.0.0",visibility=["//visibility:public"])']
    (output / 'BUILD.bazel').write_text('\n'.join(lines) + '\n')
    return dict(module='jit_source_runtime', references='@jit_source_runtime//:references',
        host='@jit_source_runtime//:host', coreRoot='@jit_source_runtime//:core_root',
        copiedInputs=len(wanted), compilationNodes=sum(bool(config.get('OutputDirectories') or config.get('OutputFiles'))
            for project in contract['Projects'].values() for config in project.get('Configurations', [project])))
