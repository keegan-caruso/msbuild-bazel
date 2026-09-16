"""Acquire frozen inputs and provenance after qualify-local-mvp.sh restores packages."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from discovery_contract import SDK

REVISION = '49b5339ce85385dc52d4d8e8f2b8308becf23506'
PACKAGES = ('polysharp/1.15.0', 'microsoft.net.illink.tasks/10.0.11')
FILES = {
    'App/App.csproj': '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Shared/Shared.csproj"/></ItemGroup></Project>',
    'App/Program.cs': 'System.Console.WriteLine(Value.Text);',
    'Shared/Shared.csproj': '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>',
    'Shared/Value.cs': 'public class Value { public static string Text => "mvp-calibration"; }',
    'Directory.Build.props': '<Project/>',
    'Directory.Build.targets': '<Project/>',
}


def output(*command):
    return subprocess.check_output(list(map(str, command)), text=True)


def restore(source, project):
    subprocess.run([str(SDK / 'dotnet'), 'restore', str(source / project),
        '-p:Configuration=Release', '-p:TargetFramework=net10.0',
        '--packages', str(source / '.nuget/packages')], cwd=source, check=True)


def library(root, source, archive):
    source.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(source, filter='data')
    for package in PACKAGES:
        shutil.copytree(root / 'p' / package, source / '.nuget/packages' / package)
    restore(source, 'src/Serilog/Serilog.csproj')


def main(root):
    small, large = root / 'small', root / 'serilog'
    small.mkdir()
    for name, content in FILES.items():
        path = small / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (small / '.nuget/packages').mkdir(parents=True)
    restore(small, 'App/App.csproj')
    archive = subprocess.check_output(['git', '-C', str(root / 'upstream'), 'archive', REVISION])
    library(root, large, archive)
    for source, project in [(small, 'App/App.csproj'), (large, 'src/Serilog/Serilog.csproj')]:
        (root / (source.name + '-entries.json')).write_text(json.dumps([
            dict(project=project, globalProperties=dict(Configuration='Release', TargetFramework='net10.0'))]) + '\n')

    nix_store = '/nix/var/nix/profiles/default/bin/nix-store'
    closure = output(nix_store, '-qR', SDK.parents[1]).splitlines()
    receipt = dict(
        candidateRevision=output('git', 'rev-parse', 'HEAD').strip(),
        sourceRevision=REVISION,
        sourceArchiveSha256=hashlib.sha256(archive).hexdigest(),
        smallAuthoredSha256={name: hashlib.sha256(content.encode()).hexdigest() for name, content in FILES.items()},
        packages={str(p.relative_to(root / 'p')): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted((root / 'p').rglob('*.nupkg'))},
        sdkRoot=str(SDK), sdkInfo=output(SDK / 'dotnet', '--info'),
        msbuild=output(SDK / 'dotnet', 'msbuild', '-version', '-nologo'),
        bazel=output(os.environ['RULES_MSBUILD_BAZEL'], '--batch', 'version', '--gnu_format'),
        nixClosure=[(p, output(nix_store, '--query', '--hash', p).strip()) for p in closure],
        osBuild=output('/usr/bin/sw_vers'),
        acquisition='New package cache and DOTNET_CLI_HOME; ambient HOME and system Nix store retained')
    (root / 'acquisition-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

    # Package mutation controls need a separate restore-only tree.
    library(root, root / 'sc4', archive)
    assert not (root / 'sc4/src/Serilog/obj/Release').exists()


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
