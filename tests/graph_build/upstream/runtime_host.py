"""Add a bounded source-only corerun consumer to a qualified runtime graph.

Native producers use declared archives. Managed host libraries and the executable
probe use public graph actions; no installed runtime payload enters the layout.
"""
import argparse
import json
import os
from pathlib import Path
import shutil


def declare_native(root, native, names):
    def copy_input(source, destination):
        if Path(source).name in ['source.tar', 'toolchain.tar']:
            try:
                os.link(source, destination)
                return destination
            except OSError:
                pass
        return shutil.copy2(source, destination)
    for name in names:
        # Copy mutable declarations; only large verified archives are linked.
        shutil.copytree(native / name, root / name, copy_function=copy_input)
        adapter = Path(__file__).resolve().parents[2] / 'runtime'
        shutil.copyfile(adapter / 'native_action.bzl', root / name / 'native_action.bzl')
        declaration = root / name / 'BUILD.bazel'
        lines = declaration.read_text().splitlines()
        assert 'native_graph_driver(name="driver")' in lines
        declaration.write_text('\n'.join(lines) + '\n')
        (root / name / 'driver-contract.json').write_text(json.dumps(dict(
            Version=1, Entry='Task.csproj', SdkVersion='10.0.400',
            Properties=dict(Configuration='Release'), SharedInputs=[],
            Projects={'Task.csproj': dict(Inputs=['Task.csproj', 'NativeBuild.cs'], OutputDirectories=['bin/Release/net10.0', 'obj/Release/net10.0'])}), indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('native_workspace', type=Path)
    args = parser.parse_args()
    assert os.uname().sysname == "Linux" and os.uname().machine == "aarch64", "Qualification requires Linux ARM64"
    root, native = args.workspace.resolve(), args.native_workspace.resolve()
    contract = json.loads((root / 'graph.generated.json').read_text())
    assert contract['SdkVersion'] == '10.0.400'
    metadata = json.loads((native / 'native/acquisition.json').read_text())
    assert metadata['commit'] == '60629d14374c56f1cb51819049ad1fa529307f8d'
    assert metadata['jobs'] == 4 and metadata['generator'] == 'Ninja'
    projects = ['src/coreclr/System.Private.CoreLib/System.Private.CoreLib.csproj',
                'src/libraries/System.Runtime/src/System.Runtime.csproj']
    assert all(path in contract['Projects'] for path in projects)
    declare_native(root, native, ['native', 'native_support'])
    app = root / 'runtime_probe'
    app.mkdir(exist_ok=False)
    (app / 'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><UseAppHost>false</UseAppHost></PropertyGroup></Project>')
    (app / 'Program.cs').write_text('''return System.Environment.Version.Major == 10
    && typeof(object).Assembly.Location.Contains("runtime_source.layout")
    && System.Environment.GetEnvironmentVariable("RUNTIME_PROVIDER") == "source"
    && System.IO.File.ReadAllText(System.IO.Path.Combine(System.IO.Path.GetDirectoryName(typeof(object).Assembly.Location)!, "runtime-state.txt")) == "valid"
    && System.IO.File.ReadAllText("/proc/self/maps").Contains("runtime_source.layout/libcoreclr.so")
    && System.IO.File.ReadAllText("/proc/self/maps").Contains("runtime_source.layout/libclrjit.so")
    && System.IO.File.ReadAllText("/proc/self/maps").Contains("runtime_source.layout/libSystem.Native.so")
    ? 0 : 23;
''')
    (app / 'runtime-state.txt').write_text('valid')
    (app / 'contract.json').write_text(json.dumps(dict(
        Version=1, Entry='App.csproj', SdkVersion='10.0.400',
        Properties=dict(Configuration='Release'), SharedInputs=[],
        Projects={'App.csproj': dict(Inputs=['App.csproj', 'Program.cs'], OutputDirectories=['bin/Release/net10.0', 'obj/Release/net10.0'])}), indent=2) + '\n')
    declarations = '''
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph", "msbuild_graph_layout", "msbuild_graph_test", "msbuild_layout", "msbuild_runtime")
msbuild_graph_layout(name="runtime_corelib", graph=":graph", project="src/coreclr/System.Private.CoreLib/System.Private.CoreLib.csproj", framework="net10.0")
msbuild_graph_layout(name="runtime_system", graph=":graph", project="src/libraries/System.Runtime/src/System.Runtime.csproj", framework="net10.0")
msbuild_layout(name="runtime_source", paths={
    "runtime_probe/runtime-state.txt": "runtime-state.txt",
    "//native:host": "corerun", "//native:coreclr": "libcoreclr.so", "//native:jit": "libclrjit.so",
    "//native_support:system_native": "libSystem.Native.so",
    ":runtime_corelib": ".", ":runtime_system": ".",
})
msbuild_runtime(name="runtime_host", layout=":runtime_source", entry_point="corerun", launch_mode="corerun", runtime_identifier="linux-arm64", version="10.0.0", env={"RUNTIME_PROVIDER": "source"})
msbuild_graph(name="runtime_probe_build", runner=":graph_runner", contract="runtime_probe/contract.json", source_root="runtime_probe", srcs=["runtime_probe/App.csproj", "runtime_probe/Program.cs"], linux_stable_paths=True, linux_worker=True)
msbuild_graph_test(name="runtime_probe_test", graph=":runtime_probe_build", assembly="bin/Release/net10.0/App.dll", runtime_host=":runtime_host")
'''
    with (root / 'BUILD.bazel').open('a') as build:
        build.write(declarations)
    print(root, flush=True)


if __name__ == '__main__':
    main()
