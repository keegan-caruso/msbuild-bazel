"""Declare the native product's source, tools, version inputs and build actions."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

from .common import ROOT, read_recipe, digest

CORECLR = dict(coreclr='libcoreclr.so', jit='libclrjit.so', host='corerun', gc='libclrgc.so', gcexp='libclrgcexp.so',
    dac='libmscordaccore.so', dbi='libmscordbi.so', trace='libcoreclrtraceptprovider.so', dump='createdump')
LIBRARIES = dict(system_native='libSystem.Native.so', compression='libSystem.IO.Compression.Native.so',
    openssl='libSystem.Security.Cryptography.Native.OpenSsl.so', globalization='libSystem.Globalization.Native.so',
    net_security='libSystem.Net.Security.Native.so')
HOST = dict(muxer='dotnet', fxr='libhostfxr.so', policy='libhostpolicy.so')


def prepare_inputs(output, source, toolchain=None, sandbox=None):
    output.mkdir(parents=True,exist_ok=False)
    recipe=read_recipe()
    if digest(source)!=recipe['source']['sha256']:
        raise ValueError('Source archive differs from the pinned runtime')
    value=dict(source=dict(urls=[source.resolve().as_uri(),recipe['source']['url']],sha256=recipe['source']['sha256'],commit=recipe['source']['revision']))
    if toolchain:
        if not sandbox:
            raise ValueError('Provide a sandbox executable with the native toolchain archive')
        value['archive']=dict(url=toolchain.resolve().as_uri(),sha256=digest(toolchain))
        value['sandbox']=dict(url=sandbox.resolve().as_uri(),sha256=digest(sandbox))
    else:
        value['packages']=json.loads((ROOT/'tests/runtime/native-packages.json').read_text())['packages']
    (output/'inputs.json').write_text(json.dumps(value,indent=2)+'\n')


def declare_inputs(root, preparation):
    value=json.loads((preparation/'inputs.json').read_text())
    folder=root/'native';folder.mkdir()
    here=ROOT/'tests/runtime'
    for source,target in [('NativeBuild.cs.txt','NativeBuild.cs'),('NativePreparation.cs.txt','NativePreparation.cs'),('native_action.bzl','native_action.bzl')]:
        shutil.copyfile(here/source,folder/target)
    shutil.copyfile(here/'native_inputs.bzl',folder/'native_inputs.bzl')
    (folder/'Task.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><StartupObject>NativePreparation</StartupObject></PropertyGroup></Project>')
    sys.path.insert(0,str(here))
    from native_driver import write_contract
    write_contract(folder,['NativePreparation.cs'])
    shutil.copyfile(here/'source_repository.bzl',root/'source_repository.bzl')
    source=value['source']
    module=['runtime_source=use_repo_rule("//:source_repository.bzl","runtime_source")',
        'http_file=use_repo_rule("@bazel_tools//tools/build_defs/repo:http.bzl","http_file")',
        'runtime_source(name="runtime_source",urls='+json.dumps(source['urls'])+',sha256='+json.dumps(source['sha256'])+',commit='+json.dumps(source['commit'])+')']
    packages={}
    for item in value.get('packages',[]):
        name='runtime_tool_'+item['name'].replace('-','_').replace('+','p')
        module.append('http_file(name='+json.dumps(name)+',url='+json.dumps(item['url'])+',sha256='+json.dumps(item['sha256'])+',downloaded_file_path='+json.dumps(item['name']+'.deb')+')')
        packages['@'+name+'//file']=item['sha256']
    if packages:
        toolchain=':toolchain';sandbox=':bwrap'
        provenance=dict(kind='packages',packagesSha256=hashlib.sha256(json.dumps(value['packages'],sort_keys=True).encode()).hexdigest())
    else:
        for name,item,filename,executable in [('runtime_native_tools',value['archive'],'toolchain.tar',False),('runtime_native_sandbox',value['sandbox'],'bwrap',True)]:
            module.append('http_file(name='+json.dumps(name)+',url='+json.dumps(item['url'])+',sha256='+json.dumps(item['sha256'])+',downloaded_file_path='+json.dumps(filename)+',executable='+str(executable)+')')
        toolchain='@runtime_native_tools//file';sandbox='@runtime_native_sandbox//file'
        provenance=dict(kind='archive',sha256=value['archive']['sha256'])
    with (root/'MODULE.bazel').open('a') as output:
        output.write('\n'+'\n'.join(module)+'\n')
    lines=['load(":native_action.bzl","native_graph_driver","native_runtime")',
        'load(":native_inputs.bzl","native_inputs")',
        'native_graph_driver(name="driver",sources=["NativePreparation.cs"])',
        'native_inputs(name="sources",commit='+json.dumps(source['commit'])+',packages='+json.dumps(packages)+')',
        'filegroup(name="sandbox",srcs=['+json.dumps(sandbox)+'],visibility=["//visibility:public"])']
    commit=source['commit']
    for component,products,script in [
        ('coreclr',CORECLR,'./src/coreclr/build-runtime.sh -arm64 -release -component runtime -component jit -component hosts -numproc 4 -ninja\nmkdir result\n'+''.join('cp artifacts/bin/coreclr/linux.arm64.Release/'+name+' result/\n' for name in CORECLR.values())),
        ('libraries',LIBRARIES,'./src/native/libs/build-native.sh -arm64 -release -outconfig qualification -configureonly -numproc 4 -ninja\ncmake --build artifacts/obj/native/qualification --target System.Native System.IO.Compression.Native System.Security.Cryptography.Native.OpenSsl System.Globalization.Native System.Net.Security.Native --parallel 4\nmkdir result\n'+''.join('cp artifacts/obj/native/qualification/'+name.removeprefix('lib').removesuffix('.so').removesuffix('.OpenSsl')+'/'+name+' result/\n' for name in LIBRARIES.values())),
        ('host',HOST,'./src/native/corehost/build.sh -arm64 -release -commithash '+commit+' -numproc 4 -ninja\nmkdir result\n'+''.join('cp artifacts/bin/linux-arm64.Release/corehost/'+name+' result/\n' for name in HOST.values())),
    ]:
        (folder/(component+'.sh')).write_text('set -euo pipefail\n'+script+'tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -cf result.tar -C result .\n')
        lines.append('native_runtime(name='+json.dumps('runtime_'+component)+',driver=":driver",sandbox='+json.dumps(sandbox)+',toolchain_archive='+json.dumps(toolchain)+',source_archive=":sources",script='+json.dumps(component+'.sh')+',products='+json.dumps(products)+')')
        for group in products:
            label=group if component=='coreclr' else component+'_'+group
            lines.append('filegroup(name='+json.dumps(label)+',srcs=['+json.dumps(':runtime_'+component)+'],output_group='+json.dumps(group)+',visibility=["//visibility:public"])')
    (folder/'BUILD.bazel').write_text('\n'.join(lines)+'\n')
    for component,products in [('libraries',LIBRARIES),('host',HOST)]:
        target=root/component;target.mkdir()
        (target/'BUILD.bazel').write_text(''.join('alias(name='+json.dumps(group)+',actual='+json.dumps('//native:'+component+'_'+group)+',visibility=["//visibility:public"])\n' for group in products))
    return provenance
