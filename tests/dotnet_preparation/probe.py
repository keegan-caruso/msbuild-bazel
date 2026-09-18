"""Real restore/export/preparation parity and optional native Bazel acceptance."""
import argparse
import ast
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_graph import prepare
from bazel_events import json_stream


def declarations(path):
    result = []
    for statement in ast.parse(path.read_text()).body:
        call = statement.value
        if call.func.id == 'load':
            continue
        attributes = {item.arg: ast.literal_eval(item.value) for item in call.keywords}
        if 'framework_selections' in attributes:
            attributes['framework_selections'] = json.loads(attributes['framework_selections'])
        result.append((call.func.id, attributes))
    return result


def probe(output, bazel=False, packages=False):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sdk = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT / '.tools/dotnet')).resolve()
    dotnet = sdk / 'dotnet'
    source = output / 'source'
    source.mkdir()
    (source/'.nuget/packages').mkdir(parents=True)
    files = {
        'global.json': (ROOT/'global.json').read_text(),
        'NuGet.Config': '<configuration><packageSources><clear/></packageSources></configuration>',
        'Directory.Build.props': '<Project><PropertyGroup><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><UseAppHost>false</UseAppHost><UseSharedCompilation>false</UseSharedCompilation><EnableNETAnalyzers>false</EnableNETAnalyzers><Deterministic>true</Deterministic><DisableTransitiveProjectReferences>true</DisableTransitiveProjectReferences></PropertyGroup></Project>',
        'Shared/Shared.csproj': '<Project Sdk="Microsoft.NET.Sdk"/>',
        'Shared/Value.cs': 'namespace Shared; public static class Value { public static string Text => "dotnet-preparation"; }',
        'App/App.csproj': '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Shared/Shared.csproj"/></ItemGroup></Project>',
        'App/Program.cs': 'Console.WriteLine(Shared.Value.Text);',
        'App/expected.txt': 'explicit-test-data',
    }
    for name, text in files.items():
        path = source/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    env = dict(os.environ, DOTNET_ROOT=str(sdk), DOTNET_HOST_PATH=str(dotnet), NUGET_PACKAGES=str(source/'.nuget/packages'), DOTNET_CLI_HOME=str(output/'home'), DOTNET_NOLOGO='1', DOTNET_CLI_TELEMETRY_OPTOUT='1', MSBUILDDISABLENODEREUSE='1', UseSharedCompilation='false')
    def run(label, args, cwd=ROOT, environment=env, success=True):
        result = subprocess.run(list(map(str,args)), cwd=cwd, env=environment, capture_output=True, text=True, timeout=240)
        (output/(label+'.log')).write_text(result.stdout+result.stderr)
        if success and result.returncode:
            raise RuntimeError(label+' failed: '+result.stdout+result.stderr)
        if not success and result.returncode == 0:
            raise AssertionError(label+' unexpectedly succeeded')
        return result.stdout+result.stderr
    if packages:
        package = output/'package'
        package.mkdir()
        (package/'Fixture.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><PackageId>Fixture</PackageId><Version>1.0.0</Version><UseSharedCompilation>false</UseSharedCompilation></PropertyGroup></Project>')
        (package/'Value.cs').write_text('namespace Fixture; public static class Value { public static string Text => "dotnet-preparation"; }')
        (package/'NuGet.Config').write_text('<configuration><packageSources><clear/></packageSources></configuration>')
        feed=output/'feed'
        run('pack',[dotnet,'pack',package/'Fixture.csproj','-c','Release','-o',feed,'--nologo'],package)
        (source/'NuGet.Config').write_text('<configuration><packageSources><clear/><add key="fixture" value="'+str(feed)+'"/></packageSources></configuration>')
        (source/'Shared/Shared.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><PackageReference Include="Fixture" Version="[1.0.0]"/></ItemGroup></Project>')
        (source/'Shared/Value.cs').write_text('namespace Shared; public static class Value { public static string Text => Fixture.Value.Text; }')
    for tool in ('Preparation','GraphExport'):
        run('build-'+tool, [dotnet,'build',ROOT/'tools'/tool,'-c','Release','-p:UseSharedCompilation=false','--nologo'])
    run('restore', [dotnet,'restore',source/'App/App.csproj','-p:Configuration=Release','--nologo'],source)
    export_request = output/'export-request.json'
    export_request.write_text(json.dumps(dict(schemaVersion=1,workspace=str(source),dotnetRoot=str(sdk),sdkVersion='10.0.400',packageRoot=str(source/'.nuget/packages'),entryPoints=[dict(project='App/App.csproj',globalProperties={'Configuration':'Release'})],output=str(output/'graph.json'))))
    run('export',[dotnet,ROOT/'tools/GraphExport/bin/Release/net10.0/GraphExport.dll','--request',export_request],source)
    graph=json.loads((output/'graph.json').read_text())
    app=next(node['id'] for node in graph['nodes'] if node['project']=='workspace/App/App.csproj')
    tests=[dict(node=app,data=['App/expected.txt'],expectedTests=['Explicit.Declared.Test'])]
    request=dict(schemaVersion=1,repository=str(ROOT),workspace=str(source),manifest=str(output/'graph.json'),output=str(output/'dotnet'),sdkRoot=str(sdk),tests=tests,compileBoundary=not packages)
    request_path=output/'request.json';request_path.write_text(json.dumps(request))
    # MSBuild's explicit SDK process paths work without Python or other PATH tools.
    empty_path=output/'empty-path';empty_path.mkdir()
    restricted=dict(env,PATH=str(empty_path))
    run('prepare-dotnet',[dotnet,ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll','prepare','--request',request_path],environment=restricted)
    prepare(source,output/'graph.json',output/'python',tests=tests,compile_boundary=not packages,environment=env)
    assert declarations(output/'dotnet/BUILD.bazel')==declarations(output/'python/BUILD.bazel')
    assert declarations(output/'dotnet/MODULE.bazel')==declarations(output/'python/MODULE.bazel')
    for relative in ['graph.json','tests.json',*[str(p.relative_to(output/'dotnet')) for p in (output/'dotnet/package-manifests').glob('*.json')]]:
        assert json.loads((output/'dotnet'/relative).read_text())==json.loads((output/'python'/relative).read_text()),relative
    for folder in ('src','runner','test-runner','test-data','packages'):
        left={str(p.relative_to(output/'dotnet'/folder)):p.read_bytes() for p in (output/'dotnet'/folder).rglob('*') if p.is_file()}
        right={str(p.relative_to(output/'python'/folder)):p.read_bytes() for p in (output/'python'/folder).rglob('*') if p.is_file()}
        assert left==right,folder
    for path in (output/'dotnet/restore').glob('*.json'):
        left=json.loads(path.read_text());right=json.loads((output/'python/restore'/path.name).read_text())
        assert set(left)==set(right)
        for key in left:
            if key.endswith('.json') or key.endswith('.cache'):
                assert json.loads(left[key])==json.loads(right[key]),key
            else: assert left[key]==right[key],key
    run('baseline',[dotnet,'build',source/'App/App.csproj','-c','Release','--no-restore','--nologo'],source)
    baseline=run('baseline-app',[dotnet,source/'App/bin/Release/net10.0/App.dll'],source).strip()
    executed=[]
    if bazel:
        executable=Path(os.environ.get('RULES_MSBUILD_BAZEL',ROOT/'.tools/bin/bazel'))
        strategy='darwin-sandbox' if platform.system()=='Darwin' else 'linux-sandbox'
        log=output/'execution.json'
        run('bazel',[executable,'--batch','--nohome_rc','--noworkspace_rc','--output_base='+str(output/'b'),'--output_user_root='+str(output/'u'),'build','//:all','--spawn_strategy='+strategy,'--strategy=MsbuildProject='+strategy,'--jobs=2','--noshow_progress','--color=no','--curses=no','--execution_log_json_file='+str(log)],output/'dotnet')
        actual=run('bazel-app',[dotnet,output/f'dotnet/bazel-bin/node_{app}.bundle/artifacts/App/bin/Release/net10.0/App.dll']).strip()
        assert actual==baseline=='dotnet-preparation'
        executed=[r['targetLabel'] for r in json_stream(log) if r.get('mnemonic')=='MsbuildProject' and not r.get('cacheHit')]
        assert len(executed)==2,executed
    # New glob inputs must be rejected even though every old input still hashes.
    (source/'Shared/New.cs').write_text('namespace Shared; public class New {}')
    request['output']=str(output/'stale');request_path.write_text(json.dumps(request))
    rejected=run('new-glob-rejection',[dotnet,ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll','prepare','--request',request_path],environment=restricted,success=False)
    assert 'stale-manifest' in rejected and not (output/'stale').exists(),rejected
    report=dict(managedPackage=packages,preparationParity=True,pythonAbsentFromPreparationPath=True,baseline=baseline,testDataParity=True,restoreParity=True,newGlobRejected=True,executedProjects=executed,nativeBazel=bazel)
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--bazel',action='store_true')
    parser.add_argument('--packages',action='store_true')
    args=parser.parse_args();probe(args.output,args.bazel,args.packages)
