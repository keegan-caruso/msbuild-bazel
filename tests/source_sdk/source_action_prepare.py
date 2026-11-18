"""Prepare declared inputs for a coarse, offline upstream SDK source-build action.

Qualification tooling only. The SDK build is one Bazel action here; this does not
claim incremental component scheduling. Input archives retain separate source,
bootstrap and native-tool identities.
"""
import argparse
import base64
import io
import json
from pathlib import Path
import platform
import posixpath
import shutil
import subprocess
import sys
import tarfile
import textwrap

from inventory import digest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from native_environment import build_prefix


def normalize(entry):
    entry.pax_headers = {key: value for key, value in entry.pax_headers.items()
                         if key not in {"path", "linkpath", "mtime", "atime", "ctime", "uid", "gid", "uname", "gname"}}
    entry.uid = entry.gid = 0
    # ZIP/NuGet cannot represent timestamps before 1980.
    entry.mtime = 315532800
    entry.uname = entry.gname = ''
    if entry.issym() and entry.linkname.startswith('/'):
        entry.linkname = posixpath.relpath(entry.linkname, '/' + posixpath.dirname(entry.name))
    return entry


def platform_configuration(architecture):
    platforms = {
        "arm64": ("aarch64", "aarch64"),
        "x64": ("x86_64", "x86_64"),
    }
    if architecture not in platforms:
        raise ValueError("Unsupported source SDK architecture: " + architecture)
    machine, cpu = platforms[architecture]
    return {"architecture": architecture, "machine": machine, "cpu": cpu,
            "rid": "linux-" + architecture}


def validate_bootstrap_host(path, architecture):
    # The .NET host must match the selected native producer, independently of version.
    with path.open('rb') as stream:
        header = stream.read(20)
    platform_configuration(architecture)
    expected = 183 if architecture == 'arm64' else 62
    if (len(header) != 20 or header[:6] != b'\x7fELF\x02\x01' or
            int.from_bytes(header[18:20], 'little') != expected):
        raise ValueError('Bootstrap SDK host architecture mismatch')


def write_bazel_files(w, rules, architecture="arm64", system_bwrap=False):
    configuration = platform_configuration(architecture)
    controller = 'dotnet.sdk(name="controller",version="10.0.400",platforms=["linux-arm64"])'
    if architecture == "x64":
        pin = json.loads(Path(__file__).with_name('pin-linux-x64.json').read_text())
        driver = pin['controllerSdk']
        integrity = 'sha256-' + base64.b64encode(bytes.fromhex(driver['sha256'])).decode()
        controller = ('dotnet.sdk_archive(name="controller",version="10.0.400",runtime_version=' +
                      json.dumps(driver['runtimeVersion']) + ',platform="linux-x64",urls=[' +
                      json.dumps(driver['url']) + '],integrity=' + json.dumps(integrity) + ')')
    (w / 'MODULE.bazel').write_text(textwrap.dedent('''\
    module(name="source_sdk_action")
    bazel_dep(name="platforms",version="1.0.0")
    bazel_dep(name="rules_msbuild",version="0.0.0")
    local_path_override(module_name="rules_msbuild",path=%s)
    dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")
    %s
    use_repo(dotnet,"controller")
    register_toolchains("//:produced_registered","//:produced_runtime_registered")
    ''') % (json.dumps(str(rules)), controller))
    (w / 'BUILD.bazel').write_text(textwrap.dedent('''\
    load(":source_action.bzl","source_sdk","sdk_layout")
    load("@rules_msbuild//msbuild:sdk.bzl","msbuild_sdk")
    load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph", "msbuild_graph_runner", "msbuild_graph_test")
    source_sdk(name="sdk",%sdriver_sdk="@controller//:sdk_host",driver_project="Driver.csproj",driver_source="Driver.cs",sandbox="bwrap",native_tools="native.tar",sources="sources.tar",bootstrap="bootstrap.tar",exec_compatible_with=["@platforms//os:linux","@platforms//cpu:%s"])
    filegroup(name="evidence",srcs=[":sdk"],output_group="evidence")
    filegroup(name="driver",srcs=[":sdk"],output_group="driver")
    sdk_layout(name="layout",archive=":sdk")
    filegroup(name="dotnet",srcs=[":layout"],output_group="dotnet")
    msbuild_sdk(name="produced",dotnet=":dotnet",files=[":layout"],sdk_version="10.0.100",runtime_version="10.0.0",runtime_identifier="%s")
    msbuild_graph_runner(name="runner")
    msbuild_graph(name="graph",runner=":runner",contract="app-contract.json",srcs=["App.csproj","App.cs"],project_outputs={"App.csproj|net10.0":["bin/Release/net10.0","App.dll","Exe"]})
    msbuild_graph_test(name="smoke",graph=":graph",project="App.csproj")
    ''') % ('system_bwrap=True,' if system_bwrap else '', configuration['cpu'], configuration['rid']))


def build_script(architecture="arm64"):
    platform_configuration(architecture)
    return build_prefix(architecture) + '''
    export DOTNET_PROCESSOR_COUNT=2 DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_GENERATE_ASPNET_CERTIFICATE=false NuGetAudit=false
    patch -p1 < identitymodel.patch
    ./prep-source-build.sh --no-sdk --no-bootstrap --no-artifacts --no-prebuilts > preparation.log 2>&1 || { tail -100 preparation.log; exit 1; }
    /usr/bin/time -v -o build.time ./build.sh -sb --clean-while-building --configuration Release --arch ''' + architecture + ''' --official-build-id 20251023.11 --branding rtm --source-repository https://github.com/dotnet/dotnet --source-version b0f34d51fccc69fd334253924abd8d6853fad7aa /p:BuildInParallel=false > build.log 2>&1 || { tail -120 build.log; grep -R -m2 "error NU" artifacts/log src/source-build-reference-packages/artifacts/log 2>/dev/null | head -40 || true; exit 1; }
    mapfile -t archives < <(find artifacts/assets/Release/Sdk -name 'dotnet-sdk-*.tar.gz')
    test "${#archives[@]}" = 1
    mkdir result
    cp "${archives[0]}" result/sdk.tar.gz
    artifacts/obj/extracted-dotnet-sdk/dotnet --info > sdk-info.txt
    tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -cf result.tar preparation.log build.log build.time sdk-info.txt artifacts/log
    '''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source_archive', type=Path)
    p.add_argument('prepared_baseline', type=Path)
    p.add_argument('directory', type=Path)
    p.add_argument('--native-tools', type=Path)
    p.add_argument('--native-tools-sha256')
    p.add_argument('--sandbox', type=Path)
    p.add_argument('--sandbox-sha256')
    p.add_argument('--system-bwrap', action='store_true')
    p.add_argument('--architecture', choices=['arm64', 'x64'], default='arm64')
    a = p.parse_args()
    configuration = platform_configuration(a.architecture)
    if platform.system() != 'Linux' or platform.machine() != configuration['machine']:
        raise ValueError('Source SDK preparation requires native ' + configuration['rid'])
    for path, expected, name in [(a.native_tools, a.native_tools_sha256, 'native tools'),
                                 (a.sandbox, a.sandbox_sha256, 'sandbox')]:
        if bool(path) != bool(expected) or (path and digest(path) != expected):
            raise ValueError('Explicit ' + name + ' requires its matching SHA256')
    if a.architecture == 'x64' and not (a.native_tools and a.sandbox):
        raise ValueError('x64 preparation requires declared native tools and sandbox inputs')
    here = Path(__file__).resolve().parent
    rules = here.parents[1]
    pin = json.loads((here / 'pin.json').read_text())
    assert digest(a.source_archive) == pin['sourceArchive']['sha256']
    baseline = a.prepared_baseline.resolve()
    validate_bootstrap_host(baseline / '.dotnet/dotnet', a.architecture)
    bootstrap_version = subprocess.check_output(
        [baseline / '.dotnet/dotnet', '--version'], cwd='/tmp', text=True).strip()
    if bootstrap_version != pin['bootstrapSdkVersion']:
        raise ValueError('Unexpected bootstrap SDK: ' + bootstrap_version)
    w = a.directory.resolve()
    w.mkdir(parents=True, exist_ok=False)


    if a.native_tools:
        shutil.copyfile(a.native_tools, w / 'native.tar')
        if digest(w / 'native.tar') != a.native_tools_sha256:
            raise ValueError('Native tools changed while staging')
    else:
        with tarfile.open(w / 'native.tar', 'w') as archive:
            for name in ['usr', 'bin', 'lib', 'sbin', 'etc/alternatives', 'etc/ld.so.conf',
                         'etc/ld.so.conf.d', 'etc/ld.so.cache', 'etc/os-release', 'etc/ssl/certs', 'etc/ssl/openssl.cnf',
                         'etc/passwd', 'etc/group', 'etc/nsswitch.conf']:
                archive.add('/' + name, arcname=name, filter=normalize)
            if Path('/lib64').exists():
                archive.add('/lib64', arcname='lib64', filter=normalize)
            for name in ['source', 'proc', 'dev', 'tmp']:
                entry = tarfile.TarInfo(name)
                entry.type, entry.mode = tarfile.DIRTYPE, 0o755
                archive.addfile(normalize(entry))

    bootstrap_archive = baseline / 'prereqs/packages/archive/Private.SourceBuilt.Artifacts.Bootstrap.tar.gz'
    assert bootstrap_archive.is_file()
    with tarfile.open(w / 'bootstrap.tar', 'w') as archive:
        archive.add(baseline / '.dotnet', arcname='.dotnet', filter=normalize)
        archive.add(bootstrap_archive, arcname='prereqs/packages/archive/Private.SourceBuilt.Artifacts.Bootstrap.tar.gz', filter=normalize)

    script = build_script(a.architecture)
    with tarfile.open(a.source_archive, 'r|gz') as original, tarfile.open(w / 'sources.tar', 'w') as archive:
        for entry in original:
            parts = entry.name.split('/', 1)
            if len(parts) < 2 or not parts[1]:
                continue
            entry.name = parts[1]
            if entry.islnk():
                entry.linkname = entry.linkname.split('/', 1)[1]
            data = original.extractfile(entry) if entry.isfile() else None
            archive.addfile(normalize(entry), data)
        for name, data in [('build-native.sh', script.encode()), ('identitymodel.patch', (here / 'patches/identitymodel-file-version.patch').read_bytes())]:
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode = len(data), 0o644
            archive.addfile(normalize(entry), io.BytesIO(data))
    shutil.copy2(a.sandbox or '/usr/bin/bwrap', w / 'bwrap')
    if a.sandbox and digest(w / 'bwrap') != a.sandbox_sha256:
        raise ValueError('Sandbox changed while staging')
    shutil.copyfile(here / 'source_action.bzl', w / 'source_action.bzl')
    shutil.copyfile(rules / 'tests/runtime/NativeBuild.cs.txt', w / 'Driver.cs')
    (w / 'Driver.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><Nullable>enable</Nullable></PropertyGroup></Project>')
    write_bazel_files(w, rules, a.architecture, a.system_bwrap)
    (w / 'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><UseAppHost>false</UseAppHost><EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup><ItemGroup><Compile Include="App.cs" /></ItemGroup></Project>')
    (w / 'App.cs').write_text('System.Console.WriteLine("SDK_FROM_SOURCE="+System.Environment.Version); return System.Environment.Version.ToString()=="10.0.0" ? 0 : 1;')
    (w / 'app-contract.json').write_text(json.dumps(dict(Version=1,Entry='App.csproj',SdkVersion='10.0.100',Properties={'Configuration':'Release'},SharedInputs=[],Projects={'App.csproj':dict(Inputs=['App.csproj','App.cs'],OutputDirectories=['bin/Release/net10.0','obj/Release/net10.0'])})))
    report = {'platform': configuration['rid'], 'systemBwrap': a.system_bwrap,
              'nativeToolsSource': 'declared-archive' if a.native_tools else 'captured-environment',
              'nativeEnvironmentSha256': digest(rules / 'tests/runtime/native_environment.py'),
              'sourceRevision': pin['sourceRevision'], 'sourceArchiveSha256': pin['sourceArchive']['sha256'],
              'bootstrapArtifactsSha256': digest(bootstrap_archive),
              'bootstrapSdkVersion': bootstrap_version,
              'inputs': {name: {'sha256': digest(w / name), 'bytes': (w / name).stat().st_size}
                         for name in ['sources.tar', 'bootstrap.tar', 'native.tar', 'bwrap']},
              'nativePackages': None if a.native_tools else subprocess.check_output(['dpkg-query', '-W'], text=True).splitlines()}
    (w / 'acquisition.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'nativePackages'}, indent=2), flush=True)


if __name__ == "__main__":
    main()
