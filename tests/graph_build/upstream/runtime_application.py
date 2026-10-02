"""Compose qualified managed/native graph products for an ordinary source-runtime app."""
import argparse
import ast
import json
import os
from pathlib import Path
import shutil

from runtime_host import declare_native

ROOT = Path(__file__).resolve().parents[3]
COMMIT = '60629d14374c56f1cb51819049ad1fa529307f8d'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path, help='fresh combined loaded-common/platform graph workspace')
    parser.add_argument('native_workspace', type=Path, help='declared native, support, host, crypto and compression producers')
    parser.add_argument('--include-private-frameworks', action='store_true', help='declare reviewed alternate-framework test support assemblies beside the source host')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    root, native = args.workspace.resolve(), args.native_workspace.resolve()
    assert not (root / 'app').exists() and not (root / 'runtime').exists()
    contract = json.loads((root / 'graph.generated.json').read_text())
    assert contract['SdkVersion'] == '10.0.400'
    # The generated macro exposes evaluated output paths; never infer host
    # ownership from a directory scan or copy an installed framework template.
    tree = ast.parse((root / 'graph.generated.bzl').read_text())
    outputs = [ast.literal_eval(keyword.value) for node in ast.walk(tree) if isinstance(node, ast.Call)
               for keyword in node.keywords if keyword.arg == 'project_outputs']
    assert len(outputs) == 1
    selection = json.loads((ROOT / 'tests/runtime/subset_slices.json').read_text())
    assert selection['commit'] == COMMIT
    shim_framework = next(item['framework'] for item in selection['slices'] if item['name'] == 'loaded-shims')
    managed, private = {}, {}
    for key, (directory, assembly, kind) in outputs[0].items():
        project, framework = key.split('|')
        if not (project.startswith('src/coreclr/System.Private.CoreLib/') or
                (project.startswith('src/libraries/') and '/src/' in project)):
            continue
        if args.include_private_frameworks and selection.get('privateFrameworks', {}).get(assembly.removesuffix('.dll')) == framework:
            assert kind == 'Library' and assembly not in private
            private[assembly] = dict(project=project, framework=framework, path=directory + '/' + assembly)
            continue
        default_framework = shim_framework if project.startswith('src/libraries/shims/') else 'net10.0'
        if framework != selection['hostFrameworks'].get(assembly.removesuffix('.dll'), default_framework):
            continue
        assert kind == 'Library' and assembly.endswith('.dll') and assembly not in managed
        managed[assembly] = dict(project=project, framework=framework, path=directory + '/' + assembly)
    required = {'System.Private.CoreLib.dll', 'System.Runtime.dll', 'System.Console.dll', 'System.Linq.dll',
                'System.Text.Json.dll', 'System.Text.Encodings.Web.dll', 'System.IO.Compression.dll',
                'System.Security.Cryptography.dll'}
    assert required <= managed.keys(), sorted(required - managed.keys())
    if args.include_private_frameworks:
        assert set(private) == {name + '.dll' for name in selection['privateFrameworks']}, 'The graph lacks reviewed private framework producers'
    names = ['native', 'native_support', 'host', 'crypto', 'compression']
    for name in names:
        metadata = json.loads((native / name / 'acquisition.json').read_text())
        assert metadata['commit'] == COMMIT and metadata['jobs'] == 4 and metadata['generator'] == 'Ninja'
    declare_native(root, native, names)
    app = root / 'app'
    shutil.copytree(ROOT / 'examples/source-runtime-app', app)
    project = app / 'App.csproj'
    project.write_text(project.read_text().replace('<OutputType>Exe</OutputType>',
        '<OutputType>Exe</OutputType><UseAppHost>false</UseAppHost><RuntimeFrameworkVersion>10.0.0</RuntimeFrameworkVersion>'))
    (app / 'contract.json').write_text(json.dumps(dict(Version=1, Entry='App.csproj', SdkVersion='10.0.400',
        Properties=dict(Configuration='Release'), SharedInputs=[], Projects={'App.csproj': dict(
            Inputs=['App.csproj', 'Program.cs'], OutputDirectories=['bin/Release/net10.0', 'obj/Release/net10.0'])}), indent=2) + '\n')
    # All graph actions remain at the workspace root; the app's source_root
    # prevents upstream Directory.Build imports from changing its semantics.
    (app / 'BUILD.bazel').unlink()
    runtime = root / 'runtime'
    shared = 'shared/Microsoft.NETCore.App/10.0.0'
    framework = runtime / shared
    framework.mkdir(parents=True)
    (framework / '.version').write_text(COMMIT + '\n10.0.0\n')
    (framework / 'Microsoft.NETCore.App.runtimeconfig.json').write_text(json.dumps({'runtimeOptions': {'tfm': 'net10.0'}}) + '\n')
    native_products = {
        'dotnet': ('//host:muxer', 'dotnet', 'host'),
        'libhostfxr.so': ('//host:fxr', 'host/fxr/10.0.0/libhostfxr.so', 'host'),
        'libhostpolicy.so': ('//host:policy', shared + '/libhostpolicy.so', 'host'),
        'libcoreclr.so': ('//native:coreclr', shared + '/libcoreclr.so', 'native'),
        'libclrjit.so': ('//native:jit', shared + '/libclrjit.so', 'native'),
        'libSystem.Native.so': ('//native_support:system_native', shared + '/libSystem.Native.so', 'native_support'),
        'libSystem.Security.Cryptography.Native.OpenSsl.so': ('//crypto:openssl', shared + '/libSystem.Security.Cryptography.Native.OpenSsl.so', 'crypto'),
        'libSystem.IO.Compression.Native.so': ('//compression:compression', shared + '/libSystem.IO.Compression.Native.so', 'compression'),
    }
    target = '.NETCoreApp,Version=v10.0/linux-arm64'
    identity = 'Microsoft.NETCore.App.Runtime.linux-arm64/10.0.0'
    products = {'runtime': {name: {} for name in sorted(managed)},
                'native': {name: {} for name, (_, destination, _) in native_products.items() if destination.startswith(shared + '/')}}
    deps = {'runtimeTarget': {'name': target, 'signature': ''}, 'compilationOptions': {},
            'targets': {'.NETCoreApp,Version=v10.0': {}, target: {identity: products}},
            'libraries': {identity: {'type': 'package', 'serviceable': True, 'sha512': ''}}}
    (framework / 'Microsoft.NETCore.App.deps.json').write_text(json.dumps(deps, indent=2) + '\n')
    declarations = ['load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph", "msbuild_graph_layout", "msbuild_graph_binary", "msbuild_graph_test", "msbuild_layout", "msbuild_runtime")']
    paths = {}
    for index, (name, producer) in enumerate(sorted(managed.items())):
        label = 'app_library_' + str(index)
        declarations.append('msbuild_graph_layout(name=' + json.dumps(label) + ', graph=":graph", project=' +
            json.dumps(producer['project']) + ', framework=' + json.dumps(producer['framework']) + ')')
        paths[':' + label] = shared
    for index, (name, producer) in enumerate(sorted(private.items())):
        label = 'app_private_' + str(index)
        declarations.append('msbuild_graph_layout(name=' + json.dumps(label) + ', graph=":graph", project=' +
            json.dumps(producer['project']) + ', framework=' + json.dumps(producer['framework']) + ')')
        paths[':' + label] = 'private'
    paths.update({label: destination for label, destination, _ in native_products.values()})
    paths.update({'runtime/' + shared + '/' + name: shared + '/' + name for name in
                  ['.version', 'Microsoft.NETCore.App.runtimeconfig.json', 'Microsoft.NETCore.App.deps.json']})
    declarations += ['msbuild_layout(name="app_source_runtime", paths=' + json.dumps(paths) + ')',
        'msbuild_runtime(name="app_host", layout=":app_source_runtime", entry_point="dotnet", runtime_identifier="linux-arm64", version="10.0.0", env={"RUNTIME_PROVIDER":"source"})',
        'msbuild_graph(name="app_build", runner=":graph_runner", contract="app/contract.json", source_root="app", srcs=["app/App.csproj","app/Program.cs"], linux_stable_paths=True, linux_worker=True)',
        'msbuild_graph_binary(name="app", graph=":app_build", assembly="bin/Release/net10.0/App.dll", runtime_host=":app_host")',
        'msbuild_graph_test(name="app_test", graph=":app_build", assembly="bin/Release/net10.0/App.dll", runtime_host=":app_host")']
    with (root / 'BUILD.bazel').open('a') as build:
        build.write('\n' + '\n'.join(declarations) + '\n')
    (root / 'application.json').write_text(json.dumps(dict(commit=COMMIT, framework='10.0.0', managed=managed, private=private,
        native={name: dict(label=label, path=path, producer=producer) for name, (label, path, producer) in native_products.items()},
        scope='selected source framework for ordinary app; not a redistributable runtime'), indent=2) + '\n')
    print(root, flush=True)


if __name__ == '__main__':
    main()
