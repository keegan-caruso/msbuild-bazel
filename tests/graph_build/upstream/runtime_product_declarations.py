"""Write only Bazel declarations; Bazel owns product metadata and verification."""
import json
from pathlib import Path
import shutil
import sys

from runtime_host import declare_native
from runtime_prepare import COMMIT, SOURCE_SHA256

ROOT = Path(__file__).resolve().parents[3]


def declare_product(root, native, product):
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
    (app/'contract.json').write_text(json.dumps(dict(Version=1,Entry='App.csproj',SdkVersion='10.0.400',
        Properties=dict(Configuration='Release'),SharedInputs=[],Projects={'App.csproj':dict(
            Inputs=['App.csproj','Program.cs'],OutputDirectories=['bin/Release/net10.0','obj/Release/net10.0'])}),indent=2)+'\n')
    shutil.copyfile(app/'runtime_product.bzl', root/'runtime_product.bzl')
    shutil.copyfile(Path(__file__).with_name('runtime_product_test.py'),root/'runtime_product_test.py')
    shared='shared/Microsoft.NETCore.App/10.0.0/'
    files={'//native:'+group:shared+name for group,name in coreclr.items() if group!='host'}
    files.update({'//libraries:'+group:shared+name for group,name in libraries.items()})
    files.update({'//host:muxer':'dotnet','//host:fxr':'host/fxr/10.0.0/libhostfxr.so','//host:policy':shared+'libhostpolicy.so'})
    provenance=dict(sourceCommit=COMMIT,sourceArchiveSha256=SOURCE_SHA256,
        build='unsigned developer runtime, IL assemblies',readyToRun=False,
        bootstrapSdk=json.loads((ROOT/'examples/source-runtime-app/source.json').read_text())['sdk'],
        nativeToolchainInputs=native_identity)
    projects=sorted(value['project']+'|'+value['framework'] for value in product['producers'].values())
    with (root/'MODULE.bazel').open('a') as module:
        module.write('bazel_dep(name="platforms",version="1.0.0")\nbazel_dep(name="rules_pkg",version="1.3.0")\nbazel_dep(name="rules_python",version="1.7.0")\n')
    with (root/'BUILD.bazel').open('a') as build:
        build.write('\nload(":runtime_product.bzl","source_runtime_application")\nsource_runtime_application(name="app",projects='+
            json.dumps(projects)+',native_files='+json.dumps(files)+',provenance='+repr(provenance)+')\n')
