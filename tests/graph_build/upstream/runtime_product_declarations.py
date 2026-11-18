"""Write only Bazel declarations; Bazel owns product metadata and verification."""
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
import shutil
import sys

from runtime_host import declare_native
from runtime_prepare import COMMIT, SOURCE_SHA256

ROOT = Path(__file__).resolve().parents[3]


def reference_packs(root, sdk_version, sdk_root):
    """Bind only net10 reference archives selected by a newer bootstrap SDK."""
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9.-]+)?', sdk_version):
        raise ValueError('Invalid selected SDK version')
    lock_path = root/'nuget.lock.json'
    lock = json.loads(lock_path.read_text()) if lock_path.exists() else None
    if lock is not None and lock.get('sdkVersion') != sdk_version:
        raise ValueError('NuGet lock SDK version differs from graph contract')
    if int(sdk_version.split('.')[0]) <= 10:
        return [], []
    if lock is None:
        raise ValueError('NuGet lock required for selected targeting packs')
    props = ET.parse(Path(sdk_root)/'sdk'/sdk_version/'Microsoft.NETCoreSdk.BundledVersions.props').getroot()
    refs = []
    for framework in ('Microsoft.NETCore.App', 'Microsoft.AspNetCore.App'):
        selected = [node for node in props.iter('KnownFrameworkReference')
                    if node.get('Include') == framework and node.get('TargetFramework') == 'net10.0']
        if len(selected) != 1 or selected[0].get('Condition'):
            raise ValueError('Expected one unconditional net10 framework reference: ' + framework)
        name, version = selected[0].get('TargetingPackName'), selected[0].get('TargetingPackVersion')
        if name != framework + '.Ref' or not version or not version.startswith('10.0.'):
            raise ValueError('Unexpected net10 targeting pack for ' + framework)
        matches = [p for p in lock['packages'] if p['id'].lower() == name.lower() and p['version'].lower() == version.lower()]
        if len(matches) != 1 or not re.fullmatch(r'[0-9a-f]{64}', matches[0]['sha256']):
            raise ValueError('Missing or ambiguous selected targeting pack: ' + name + ' ' + version)
        refs.append(matches[0])
    return (['@nuget//:' + p['id'].lower() + '__' + p['version'].lower() for p in refs],
            sorted(p['sha256'] for p in refs))


def declare_product(root, native, product):
    platform = product.get('platform', 'linux-arm64')
    if platform not in ('linux-arm64', 'linux-x64'):
        raise ValueError('Unsupported runtime product platform')
    architecture = platform.removeprefix('linux-')
    if (native/'inputs.json').exists() and json.loads((native/'inputs.json').read_text()).get('architecture', 'arm64') != architecture:
        raise ValueError('Managed/native runtime architectures differ')
    if (native/'inputs.json').exists():
        sys.path.insert(0,str(ROOT/'scripts'))
        from source_runtime.native import declare_inputs, CORECLR, LIBRARIES
        native_identity=declare_inputs(root,native)
        coreclr,libraries=CORECLR,LIBRARIES
    else:
        for name in ['native', 'libraries', 'host']:
            metadata = json.loads((native/name/'acquisition.json').read_text())
            assert metadata['commit'] == COMMIT and metadata['jobs'] == 4 and metadata['generator'] == 'Ninja'
        declare_native(root, native, ['native', 'libraries', 'host'])
        with (root/'native/BUILD.bazel').open('a') as build:
            build.write('\nfilegroup(name="sandbox",srcs=["bwrap"],visibility=["//visibility:public"])\n')
        coreclr=json.loads((native/'native/acquisition.json').read_text())['products']
        libraries=json.loads((native/'libraries/products.json').read_text())['products']
        native_identity=dict(kind='archive',sha256=json.loads((native/'native/acquisition.json').read_text())['inputs']['toolchain.tar']['sha256'])
    app = root/'app'
    shutil.copytree(ROOT/'examples/source-runtime-app', app)
    project = app/'App.csproj'
    project.write_text(project.read_text().replace('<OutputType>Exe</OutputType>',
        '<OutputType>Exe</OutputType><UseAppHost>false</UseAppHost><RuntimeFrameworkVersion>10.0.0</RuntimeFrameworkVersion>'))
    (app/'BUILD.bazel').unlink()
    assert ET.parse(project).getroot().findtext('.//TargetFramework') == 'net10.0'
    sdk_version = json.loads((root/'graph.generated.json').read_text())['SdkVersion']
    sdk_root = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT/'.tools/dotnet'))
    labels, digests = reference_packs(root, sdk_version, sdk_root)
    app_contract = dict(Version=1,Entry='App.csproj',SdkVersion=sdk_version,
        Properties=dict(Configuration='Release'),SharedInputs=[],Projects={'App.csproj':dict(
            Inputs=['App.csproj','Program.cs'],OutputDirectories=['bin/Release/net10.0','obj/Release/net10.0'])})
    if digests:
        app_contract['PackageDigests'] = digests
    (app/'contract.json').write_text(json.dumps(app_contract,indent=2)+'\n')
    shutil.copyfile(app/'runtime_product.bzl', root/'runtime_product.bzl')
    shutil.copyfile(Path(__file__).with_name('runtime_product_test.py'),root/'runtime_product_test.py')
    shutil.copyfile(ROOT/'tests/runtime/system_bwrap.py',root/'system_bwrap.py')
    system_bwrap = json.loads((native/'inputs.json').read_text()).get('systemBwrap', False) if (native/'inputs.json').exists() else False
    shared='shared/Microsoft.NETCore.App/10.0.0/'
    files={'//native:'+group:shared+name for group,name in coreclr.items() if group!='host'}
    files.update({'//libraries:'+group:shared+name for group,name in libraries.items()})
    files.update({'//host:muxer':'dotnet','//host:fxr':'host/fxr/10.0.0/libhostfxr.so','//host:policy':shared+'libhostpolicy.so'})
    provenance=dict(sourceCommit=COMMIT,sourceArchiveSha256=SOURCE_SHA256,
        build='unsigned developer runtime, IL assemblies',readyToRun=False,
        bootstrapSdk=json.loads((ROOT/'examples/source-runtime-app'/('source.json' if architecture == 'arm64' else 'source-x64.json')).read_text())['sdk'],
        nativeToolchainInputs=native_identity)
    projects=sorted(value['project']+'|'+value['framework'] for value in product['producers'].values())
    with (root/'MODULE.bazel').open('a') as module:
        module.write('bazel_dep(name="platforms",version="1.0.0")\nbazel_dep(name="rules_pkg",version="1.3.0")\nbazel_dep(name="rules_python",version="1.7.0")\n')
    with (root/'BUILD.bazel').open('a') as build:
        build.write('\nload(":runtime_product.bzl","source_runtime_application")\nsource_runtime_application(name="app",projects='+
            json.dumps(projects)+',system_bwrap='+str(system_bwrap)+',runtime_identifier='+json.dumps(platform)+',native_files='+json.dumps(files)+',provenance='+repr(provenance)+',reference_packs='+json.dumps(labels)+')\n')
