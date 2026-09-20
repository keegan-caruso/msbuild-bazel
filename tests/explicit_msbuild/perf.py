"""Paired Linux graph timings. Bootstrap/downloads are outside measured builds."""
import argparse
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
BAZEL = Path(os.environ['RULES_MSBUILD_BAZEL'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--sizes', default='2,32,128')
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    results = []
    def command(argv, cwd, log):
        start = time.perf_counter()
        p = subprocess.run(list(map(str, argv)), cwd=cwd, capture_output=True, text=True, timeout=1200)
        elapsed = time.perf_counter()-start
        log.write_text(p.stdout+p.stderr)
        if p.returncode: raise RuntimeError(str(log)+': '+(p.stdout+p.stderr)[-3000:])
        return elapsed
    for size in map(int, args.sizes.split(',')):
        folder = output/str(size); folder.mkdir(exist_ok=True)
        source = folder/'bazel'; source.mkdir(exist_ok=True)
        def put(path, text):
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        put(source/'MODULE.bazel', f'''module(name="explicit_perf")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(str(SDK))},include_runtime_closure=False)
register_toolchains("//:registered")
''')
        put(source/'BUILD.bazel', '''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
''')
        put(source/'NuGet.Config','<configuration><packageSources><clear /></packageSources></configuration>')
        for i in range(size):
            name=f'P{i}'; children=[x for x in (2*i+1,2*i+2) if x<size]
            refs=''.join(f'<ProjectReference Include="../P{x}/P{x}.csproj" />' for x in children)
            put(source/name/(name+'.csproj'), '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><Nullable>enable</Nullable></PropertyGroup><ItemGroup>'+refs+'</ItemGroup></Project>')
            expression=' + '.join(f'P{x}.Get()' for x in children) or '1'
            put(source/name/'Value.cs',f'public static class {name} {{ public static int Get() => {expression}; }}')
            put(source/name/'BUILD.bazel', 'load("@rules_msbuild//msbuild:defs.bzl","msbuild_library")\nmsbuild_library(name='+json.dumps(name)+',project='+json.dumps(name+'.csproj')+',target_framework="net10.0",srcs=["Value.cs"],deps='+json.dumps([f'//P{x}' for x in children])+',visibility=["//visibility:public"])\n')
        put(source/'App/App.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><Nullable>enable</Nullable></PropertyGroup><ItemGroup><ProjectReference Include="../P0/P0.csproj" /></ItemGroup></Project>')
        put(source/'App/Program.cs','System.Console.WriteLine(P0.Get());')
        put(source/'App/BUILD.bazel','load("@rules_msbuild//msbuild:defs.bzl","msbuild_binary")\nmsbuild_binary(name="App",project="App.csproj",target_framework="net10.0",srcs=["Program.cs"],deps=["//P0"])\n')
        raw=folder/'raw'; shutil.copytree(source,raw,dirs_exist_ok=True)
        worker=folder/'worker'; shutil.copytree(source,worker,dirs_exist_ok=True)
        for build_file in worker.rglob('BUILD.bazel'):
            text=build_file.read_text()
            for rule in ('msbuild_library','msbuild_binary'):
                text=text.replace(rule+'(',rule+'(linux_worker=True, ')
            build_file.write_text(text)
        def startup(engine):
            return [BAZEL,'--output_user_root='+str(folder/'user'),'--output_base='+str(folder/(engine+'-base')),'--ignore_all_rc_files']
        trees={'bazel':source,'worker':worker,'raw':raw}
        def bazel_flags(engine):
            return flags + (['--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=4'] if engine=='worker' else [])
        flags=['--jobs=4','--disk_cache=','--repository_cache='+os.environ.get('RULES_MSBUILD_REPOSITORY_CACHE','/tmp/repository-cache')]
        # Resolve repositories/start server before timing; no project compilation.
        for engine in ('bazel','worker'):
            command(startup(engine)+['build','//App','--nobuild']+bazel_flags(engine),trees[engine],folder/(engine+'-bootstrap.log'))
        rawcmd=[SDK/'dotnet','build','App/App.csproj','-c','Release','-m:4','-p:NuGetAudit=false','--nologo']
        def build(engine, case, repetition):
            log=folder/f'{case}-{engine}-{repetition}.log'
            if engine!='raw':
                argv=startup(engine)+['build','//App','--profile='+str(folder/f'{case}-{engine}-{repetition}.profile.gz')]+bazel_flags(engine)
            else: argv=rawcmd
            cwd=trees[engine]
            seconds=command(argv,cwd,log)
            results.append(dict(libraries=size,projects=size+1,case=case,engine=engine,repetition=repetition,seconds=seconds))
            (output/'results.json').write_text(json.dumps(results,indent=2))
            print(size,case,engine,repetition,round(seconds,3),flush=True)
        for case in ('cold','unchanged','leaf-body-edit'):
            for repetition in range(args.repeats):
                if case=='cold':
                    command([SDK/'dotnet','build-server','shutdown'],raw,folder/f'raw-shutdown-{repetition}.log')
                    for engine in ('bazel','worker'):
                        command(startup(engine)+['clean'],trees[engine],folder/f'{engine}-clean-{repetition}.log')
                        command(startup(engine)+['shutdown'],trees[engine],folder/f'{engine}-shutdown-{repetition}.log')
                        command(startup(engine)+['build','//App','--nobuild']+bazel_flags(engine),trees[engine],folder/f'{engine}-restart-{repetition}.log')
                    for path in list(raw.rglob('bin'))+list(raw.rglob('obj')):
                        shutil.rmtree(path)
                if case=='leaf-body-edit':
                    for tree in (source,worker,raw):
                        put(tree/f'P{size-1}/Value.cs',f'public static class P{size-1} {{ public static int Get() => {repetition+2}; }}')
                for engine in (('bazel','worker','raw') if repetition%2==0 else ('raw','worker','bazel')):
                    build(engine,case,repetition)
        # Check that each measured implementation produced the edited value.
        expected=str((size+1)//2 + args.repeats)
        for engine in ('bazel','worker'):
            log=folder/(engine+'-verify.log')
            command(startup(engine)+['run','//App']+bazel_flags(engine),trees[engine],log)
            assert expected in log.read_text().splitlines(), log
            command(startup(engine)+['shutdown'],trees[engine],folder/(engine+'-shutdown.log'))
        raw_verify=folder/'raw-verify.log'
        command([SDK/'dotnet',raw/'App/bin/Release/net10.0/App.dll'],raw,raw_verify)
        assert raw_verify.read_text().strip() == expected, raw_verify
    summary=[]
    for size in map(int,args.sizes.split(',')):
        for case in ('cold','unchanged','leaf-body-edit'):
            row=dict(projects=size+1,case=case)
            for engine in ('bazel','worker','raw'):
                row[engine]=statistics.median(r['seconds'] for r in results if r['libraries']==size and r['case']==case and r['engine']==engine)
            row['fresh_vs_raw']=row['bazel']/row['raw']; row['worker_vs_raw']=row['worker']/row['raw']; row['worker_speedup']=row['bazel']/row['worker']; summary.append(row)
    (output/'summary.json').write_text(json.dumps(summary,indent=2))


if __name__=='__main__': main()
