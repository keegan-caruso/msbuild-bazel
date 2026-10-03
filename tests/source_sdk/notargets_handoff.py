"""Package the pinned upstream NoTargets text payload and execute it as an SDK.

This slice retains upstream payload files and ManualNuspec.targets. An explicit
adapter supplies the text-only packaging properties normally supplied by Arcade;
it does not qualify the complete upstream reference-package build.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tests'))
from fixture_sdk import sdk_declarations

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('inputs',type=Path)
parser.add_argument('directory',type=Path)
parser.add_argument('--acquire', action='store_true', help='Acquire the pinned upstream text payload into a new inputs directory')
a = parser.parse_args()
pin = json.loads(Path(__file__).with_name('pin.json').read_text())
if a.acquire:
    a.inputs.mkdir(parents=True, exist_ok=False)
    prefix = 'https://raw.githubusercontent.com/dotnet/dotnet/'+pin['sourceRevision']+'/src/source-build-reference-packages/'
    for name, expected in pin['noTargetsInputHashes'].items():
        upstream = 'eng/ManualNuspec.targets' if name == 'ManualNuspec.targets' else 'src/textOnlyPackages/src/microsoft.build.notargets/3.7.0/'+name.removeprefix('payload/')
        with urlopen(prefix+upstream, timeout=60) as response:
            data = response.read()
        assert hashlib.sha256(data).hexdigest() == expected, name
        target = a.inputs/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
for name, expected in pin['noTargetsInputHashes'].items():
    assert hashlib.sha256((a.inputs/name).read_bytes()).hexdigest() == expected, name
folder = a.directory.resolve()
w = folder/'src'
w.mkdir(parents=True,exist_ok=False)
shutil.copytree(a.inputs/'payload',w/'producer')
(w/'bindings').mkdir()
shutil.copyfile(a.inputs/'ManualNuspec.targets',w/'bindings/ManualNuspec.targets')
(w/'MODULE.bazel').write_text('module(name="notargets_source")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(ROOT))+')\n'+sdk_declarations())
(w/'bindings/pack.targets').write_text('''<Project>
<PropertyGroup><IsTextOnlyPackage>true</IsTextOnlyPackage><BaseOutputPath>$(BaseIntermediateOutputPath)text-pack/</BaseOutputPath><IncludeBuildOutput>false</IncludeBuildOutput><NoDefaultExcludes>true</NoDefaultExcludes><DisableImplicitFrameworkReferences>true</DisableImplicitFrameworkReferences><PackageOutputPath>bin/packages/</PackageOutputPath><NoBuild>true</NoBuild><NoWarn>$(NoWarn);NU5125;NU5128;NU5048;NU5131</NoWarn></PropertyGroup>
<Import Project="ManualNuspec.targets" />


</Project>''')
producer = w/'producer/Microsoft.Build.NoTargets.3.7.0.csproj'
producer.write_text(producer.read_text().replace('</Project>','<Import Project="../bindings/pack.targets" /></Project>'))
inputs = sorted(str(p.relative_to(w)) for p in (w/'producer').rglob('*') if p.is_file())+['bindings/pack.targets','bindings/ManualNuspec.targets']
(w/'producer-contract.json').write_text(json.dumps(dict(Version=1,Entry='producer/Microsoft.Build.NoTargets.3.7.0.csproj',SdkVersion='10.0.400',Properties={'Configuration':'Release','DisableImplicitFrameworkReferences':'true','TargetFramework':'netstandard2.0','BaseIntermediateOutputPath':'../intermediate/'},SharedInputs=['bindings/pack.targets','bindings/ManualNuspec.targets'],Projects={'producer/Microsoft.Build.NoTargets.3.7.0.csproj':dict(Inputs=[p for p in inputs if p.startswith('producer/')],OutputDirectories=['producer/bin/packages','intermediate/Release/netstandard2.0','intermediate/text-pack'])})))
(w/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph","msbuild_graph_runner","msbuild_graph_output","msbuild_generated_nuget_package")\nmsbuild_graph_runner(name="runner")\nmsbuild_graph(name="package_graph",target="Pack",runner=":runner",contract="producer-contract.json",srcs='+json.dumps(inputs)+')\nmsbuild_graph_output(name="pack",graph=":package_graph",path="producer/bin/packages/Microsoft.Build.NoTargets.3.7.0.nupkg")\nmsbuild_generated_nuget_package(name="package",package_id="Microsoft.Build.NoTargets",version="3.7.0",archive=":pack",visibility=["//visibility:public"])\n')
(w/'consumer').mkdir()
(w/'consumer/Consumer.csproj').write_text('''<Project Sdk="Microsoft.Build.NoTargets/3.7.0"><PropertyGroup><TargetFramework>net10.0</TargetFramework><ProofFile>out/proof.txt</ProofFile></PropertyGroup><Target Name="VerifySourceSdk" BeforeTargets="Build"><Error Condition="'$(UsingMicrosoftNoTargetsSdk)' != 'true'" Text="Source SDK was not imported"/><WriteLinesToFile File="$(ProofFile)" Lines="SOURCE_NOTARGETS=$(UsingMicrosoftNoTargetsSdk)" Overwrite="true" /></Target></Project>''')
(w/'consumer/contract.json').write_text(json.dumps(dict(Version=1,Entry='Consumer.csproj',SdkVersion='10.0.400',Properties={'Configuration':'Release'},SharedInputs=[],Projects={'Consumer.csproj':dict(Inputs=['Consumer.csproj'],OutputDirectories=['out'])})))
(w/'consumer/BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph","msbuild_graph_runner","msbuild_graph_output","msbuild_package_lock")
msbuild_package_lock(name="lock",packages=["//:package"])
msbuild_graph_runner(name="runner")
msbuild_graph(name="graph",runner=":runner",contract="contract.json",source_root="consumer",srcs=["Consumer.csproj"],package_lock=":lock")
msbuild_graph_output(name="proof",graph=":graph",path="out/proof.txt")
''')
base=[os.environ['RULES_MSBUILD_BAZEL'],'--output_base='+str(folder/'base'),'--ignore_all_rc_files']
cases = []


def build(case, expected_success=True):
    result = subprocess.run(base + ['build', '//consumer:proof', '--jobs=2', '--lockfile_mode=off'],
                            cwd=w, capture_output=True, text=True, timeout=600)
    log = result.stdout + result.stderr
    (folder / (case + '.log')).write_text(log)
    assert (result.returncode == 0) == expected_success, str(folder / (case + '.log'))
    cases.append({'case': case, 'exitCode': result.returncode})
    return log


try:
    build('source-sdk')
    proof = w / 'bazel-bin/consumer/proof/proof.txt'
    assert proof.read_text().strip() == 'SOURCE_NOTARGETS=true'
    project = w / 'consumer/Consumer.csproj'
    original = project.read_text()
    project.write_text(original.replace('Microsoft.Build.NoTargets/3.7.0', 'Microsoft.Build.NoTargets/99.0.0'))
    failure = build('unavailable-sdk-version', expected_success=False)
    assert '99.0.0' in failure and 'SDK' in failure, failure
    project.write_text(original)
    props = w / 'producer/Sdk/Sdk.props'
    props.write_text(props.read_text().replace('<UsingMicrosoftNoTargetsSdk>true</UsingMicrosoftNoTargetsSdk>',
                                               '<UsingMicrosoftNoTargetsSdk>false</UsingMicrosoftNoTargetsSdk>'))
    failure = build('producer-edit-invalidates-consumer', expected_success=False)
    assert 'Source SDK was not imported' in failure, failure
    (folder / 'report.json').write_text(json.dumps({'cases': cases}, indent=2) + '\n')
    print(json.dumps(cases, indent=2))
finally:
    subprocess.run(base + ['shutdown'], cwd=w, check=True)
