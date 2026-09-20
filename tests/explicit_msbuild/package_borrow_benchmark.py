"""Linux explicit-rule copy/borrow experiment. Run in a disposable rules checkout.

Both modes retain verified worker input snapshots and a read-only compiler mount.
Only Prepare's per-project package symlink versus byte-copy operation differs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time

parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--feed',type=Path,required=True)
parser.add_argument('--projects',type=int,default=32)
parser.add_argument('--pairs',type=int,default=3)
args=parser.parse_args()
root=Path(__file__).resolve().parents[2];out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);bazel=os.environ['RULES_MSBUILD_BAZEL'];cache=os.environ['RULES_MSBUILD_REPOSITORY_CACHE']
work=Path('/tmp/explicit-borrow-experiment');work.mkdir(exist_ok=False)
workspace=work/'src';workspace.mkdir();toolroot=workspace/'tools';toolroot.mkdir()
def command(argv,cwd,log):
 start=time.monotonic();p=subprocess.run(list(map(str,argv)),cwd=cwd,text=True,capture_output=True,timeout=600)
 (out/log).write_text(p.stdout+p.stderr)
 assert p.returncode==0,(log,(p.stdout+p.stderr)[-6000:])
 return time.monotonic()-start,p.stdout+p.stderr
for mode in ['borrow','copy']:
 source=root
 if mode=='copy':
  source=work/'copy-rules';shutil.copytree(root,source,ignore=shutil.ignore_patterns('.git','bin','obj','.tools','artifacts','bazel-*'))
  program=source/'tools/ExplicitBuild/Program.cs';text=program.read_text();needle='Directory.CreateSymbolicLink(target, Real(package.Directory));';assert text.count(needle)==1
  replacement='''foreach (var file in Directory.GetFiles(Real(package.Directory), "*", SearchOption.AllDirectories))
                Copy(file, Path.Combine(target, Path.GetRelativePath(Real(package.Directory), file)));'''
  program.write_text(text.replace(needle,replacement))
  (out/'copy-variant.txt').write_text(replacement+'\n')
 command([sdk/'dotnet','build',source/'tools/ExplicitBuild','-c','Release','-warnaserror','-o',toolroot/mode],source,'tool-'+mode+'.log')
lock=work/'lock';lock.mkdir()
(lock/'Lock.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="Microsoft.CodeAnalysis.CSharp" Version="5.9.0" /></ItemGroup></Project>')
command([sdk/'dotnet','restore',lock/'Lock.csproj','--source',args.feed,'--packages',work/'nuget','-p:NuGetAudit=false'],lock,'restore.log')
assets=json.loads((lock/'obj/project.assets.json').read_text());target=assets['targets']['net10.0'];packages=workspace/'packages';packages.mkdir()
package_rules=['load("@rules_msbuild//msbuild:defs.bzl","msbuild_nuget_package")']
for key,record in target.items():
 name,version=key.split('/');archive_name=name.lower()+'.'+version+'.nupkg';archive=work/'nuget'/name.lower()/version/archive_name;shutil.copyfile(archive,packages/archive_name)
 package_rules.append('msbuild_nuget_package('+','.join(k+'='+json.dumps(v) for k,v in dict(name=name.lower(),package_id=name,version=version,archive=archive_name,archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),content_hash=assets['libraries'][key]['sha512'],deps=[':'+x.lower() for x in record.get('dependencies',{})],visibility=['//visibility:public']).items())+')')
(packages/'BUILD.bazel').write_text('\n'.join(package_rules))
(workspace/'MODULE.bazel').write_text('module(name="borrow_benchmark")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(root))+')\nsdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")\nsdk(name="dotnet",path='+json.dumps(str(sdk))+',include_runtime_closure=False)\nregister_toolchains("//:registered")\n')
(toolroot/'BUILD.bazel').write_text('package(default_visibility=["//visibility:public"])\nfilegroup(name="borrow",srcs=glob(["borrow/*"]))\nfilegroup(name="copy",srcs=glob(["copy/*"]))\nexports_files(["borrow/ExplicitBuild.dll","copy/ExplicitBuild.dll"])\n')
for index in range(args.projects):
 d=workspace/('P'+str(index));d.mkdir()
 (d/(d.name+'.csproj')).write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="Microsoft.CodeAnalysis.CSharp" Version="5.9.0" /></ItemGroup></Project>')
 (d/'Code.cs').write_text('public static class '+d.name+' { public static int Get() => int.Parse(Microsoft.CodeAnalysis.CSharp.SyntaxFactory.Literal(7).ValueText); }')
 (d/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_library")\nmsbuild_library(name='+json.dumps(d.name)+',project='+json.dumps(d.name+'.csproj')+',srcs=["Code.cs"],target_framework="net10.0",deps=["//packages:microsoft.codeanalysis.csharp"],linux_worker=True,visibility=["//visibility:public"])')
app=workspace/'App';app.mkdir()
(app/'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup>'+''.join('<ProjectReference Include="../P'+str(i)+'/P'+str(i)+'.csproj" />' for i in range(args.projects))+'</ItemGroup></Project>')
(app/'Code.cs').write_text('System.Console.WriteLine('+ '+'.join('P'+str(i)+'.Get()' for i in range(args.projects))+');')
(app/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_binary")\nmsbuild_binary(name="App",project="App.csproj",srcs=["Code.cs"],target_framework="net10.0",deps='+json.dumps(['//P'+str(i) for i in range(args.projects)])+',linux_worker=True)')
rows=[];hashes={}
for pair in range(args.pairs):
 for mode in (['borrow','copy'] if pair%2==0 else ['copy','borrow']):
  (workspace/'P0/Code.cs').write_text('public static class P0 { public static int Get() => int.Parse(Microsoft.CodeAnalysis.CSharp.SyntaxFactory.Literal(7).ValueText); }')
  (workspace/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")\nmsbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="//tools:'+mode+'/ExplicitBuild.dll",runner_support=["//tools:'+mode+'"],runtime_manifest="@dotnet//:runtime-roots.json")\ntoolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")')
  base=work/('base-'+mode+'-'+str(pair));prefix=[bazel,'--output_base='+str(base),'--ignore_all_rc_files']
  flags=['--repository_cache='+cache,'--disk_cache=','--jobs=4','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=4','--noshow_progress','--color=no','--curses=no']
  # Acquisition/extraction and repository initialization are outside timed builds.
  command(prefix+['build','//packages:all']+flags,workspace,f'{pair}-{mode}-setup.log')
  old_profiles={}
  for case in ['cold','noop','edit']:
   if case=='edit':
    p=workspace/'P0/Code.cs';p.write_text(p.read_text().replace('Literal(7)','Literal(8)'))
   elapsed,log=command(prefix+['build','//App']+flags,workspace,f'{pair}-{mode}-{case}.log')
   profiles={str(p):p.read_text() for p in (workspace/'bazel-bin').glob('*/**/worker.json')}
   changed=[json.loads(v) for k,v in profiles.items() if old_profiles.get(k)!=v];old_profiles=profiles
   expected_actions=args.projects+1 if case=='cold' else 1 if case=='edit' else 0
   assert len(changed)==expected_actions,(mode,case,len(changed),expected_actions)
   row=dict(pair=pair,mode=mode,case=case,wallSeconds=elapsed,actions=len(changed))
   for metric in ['preparationSeconds','snapshotSeconds','childSeconds','publicationSeconds','verifiedBytes','reusedBytes']:
    row[metric]=sum(p[metric] for p in changed)
   rows.append(row);(out/'measurements.json').write_text(json.dumps(rows,indent=2));print(row,flush=True)
   if case!='noop':
    binary_hashes={str(p.relative_to(workspace/'bazel-bin')):hashlib.sha256(p.read_bytes()).hexdigest() for p in (workspace/'bazel-bin').glob('*/**/*.dll') if p.name in ['App.dll']+['P'+str(i)+'.dll' for i in range(args.projects)]}
    if case not in hashes:hashes[case]=binary_hashes
    assert binary_hashes==hashes[case],(mode,case,'assembly/reference hashes differ')
  _,log=command(prefix+['run','//App']+flags,workspace,f'{pair}-{mode}-runtime.log')
  assert log.splitlines()[0]==str(args.projects*7+1),log[:1000]
  command(prefix+['shutdown'],workspace,f'{pair}-{mode}-shutdown.log')
  shutil.rmtree(base)
summary={case:{mode:{metric:statistics.median(r[metric] for r in rows if r['case']==case and r['mode']==mode) for metric in ['wallSeconds','preparationSeconds','snapshotSeconds','childSeconds','publicationSeconds']} for mode in ['copy','borrow']} for case in ['cold','noop','edit']}
(out/'summary.json').write_text(json.dumps(dict(projects=args.projects+1,packages=len(target),pairs=args.pairs,summary=summary,outputParity=True,runtimeValue=args.projects*7+1),indent=2))
print(json.dumps(summary,indent=2),flush=True)
