"""Qualify Http.Abstractions, then Immutable, in fresh Linux ARM64 workspaces.

Usage: expanded.py ASPNET_CHECKOUT RUNTIME_CHECKOUT PRIOR_QUALIFICATION OUTPUT
PRIOR_QUALIFICATION is a completed qualify.py output, or "-" to acquire the pinned
runner and prepare the bootstrap locally from clean source checkouts.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

fresh_bootstrap = sys.argv[3] == '-'
aspnet, runtime, prior, out = map(lambda p: Path(p).resolve(), sys.argv[1:])
out.mkdir(parents=True, exist_ok=False)
here = Path(__file__).resolve().parent
rules = here.parents[2]
sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
dotnet = sdk / 'dotnet'
bazel = os.environ.get('RULES_MSBUILD_BAZEL', str(rules / 'scripts/bazel-launcher.sh'))
records = []

def run(name, command, cwd=rules, env=None):
    with (out / (name + '.log')).open('w') as log:
        result = subprocess.run([str(v) for v in command], cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
    records.append(dict(case=name, exitCode=result.returncode))
    (out / 'commands.json').write_text(json.dumps(records, indent=2) + '\n')
    print(name, result.returncode, flush=True)
    result.check_returncode()

def inventory_tool(name, family, source, entry):
    probe = out / (name + '-inventory'); probe.mkdir()
    old = rules / 'tests/explicit_msbuild' / family
    (probe / 'Inventory.csproj').write_text((old / 'Inventory.csproj.txt').read_text())
    (probe / 'Program.cs').write_text((old / 'Inventory.cs.txt').read_text())
    (probe / 'selection.json').write_text(json.dumps(dict(entries=[entry], framework='net10.0')))
    run(name + '-inventory-build', [dotnet, 'build', probe / 'Inventory.csproj', '-c', 'Release'])
    run(name + '-graph', [dotnet, probe / 'bin/Release/net10.0/Inventory.dll', source, probe / 'selection.json', probe / 'inventory.json'])
    run(name + '-prepare', [sys.executable, old / 'prepare.py', source, probe / 'inventory.json', out / name, rules], env=dict(os.environ, RULES_MSBUILD_VSTEST_ARCHIVE=str(prior / 'vstest.nupkg'), RULES_MSBUILD_SYNC_INPUTS_ONLY='1' if family == 'aspnetcore' else '0'))
    return probe

for source, revision in [(aspnet, '7387de91234d3ef751fa50b3d1bfede4130213ff'), (runtime, '60629d14374c56f1cb51819049ad1fa529307f8d')]:
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip() == revision
if fresh_bootstrap:
    prior = out / 'prerequisites'
    prior.mkdir()
    runner = prior / 'vstest.nupkg'
    run('runner-acquisition', ['curl', '-fsSL', 'https://api.nuget.org/v3-flatcontainer/microsoft.testplatform.cli/17.14.1/microsoft.testplatform.cli.17.14.1.nupkg', '-o', runner])
    assert hashlib.sha256(runner.read_bytes()).hexdigest() == '3aabba2641a165f8274fbad94ed1c4e2a004877d37b2ddfab89962487f3dceab'
    run('aspnet-bootstrap', [dotnet, 'msbuild', aspnet / 'eng/tools/GenerateFiles/GenerateFiles.csproj', '-restore', '-t:GenerateDirectoryBuildFiles', '-p:Configuration=Release', '-p:NetCoreTargetingPackRoot=' + str(sdk / 'packs') + '/', '-v:minimal'])
    objtest = 'src/ObjectPool/test/Microsoft.Extensions.ObjectPool.Tests.csproj'
    run('objectpool-restore', [dotnet, 'restore', aspnet / objtest, '-p:TargetFrameworks=net10.0', '-p:Configuration=Release', '-p:NetCoreTargetingPackRoot=' + str(sdk / 'packs') + '/'])
    run('bootstrap-inventory', [sys.executable, here.parent / 'evaluation_inventory.py', aspnet, prior / 'objectpool-inventory.json', 'src/ObjectPool/src/Microsoft.Extensions.ObjectPool.csproj', objtest, 'src/Testing/src/Microsoft.AspNetCore.InternalTesting.csproj', 'eng/tools/GenerateFiles/GenerateFiles.csproj'], env=dict(os.environ, RULES_MSBUILD_INVENTORY_PROPERTIES='{"TargetFrameworks":"net10.0"}'))
http_tests = 'src/Http/Http.Abstractions/test/Microsoft.AspNetCore.Http.Abstractions.Tests.csproj'
run('http-raw', [dotnet, 'test', aspnet / http_tests, '-c', 'Release', '-f', 'net10.0', '-m:2', '-p:NetCoreTargetingPackRoot=' + str(sdk / 'packs') + '/', '-p:RepositoryCommit=7387de91234d3ef751fa50b3d1bfede4130213ff', '-p:SourceRevisionId=7387de91234d3ef751fa50b3d1bfede4130213ff', '--logger', 'trx;LogFileName=results.trx', '--results-directory', out / 'http-raw'])
inventory_tool('http', 'aspnetcore', aspnet, http_tests)
http_projects = [v['attributes']['project'] for v in json.loads((out / 'http/project-bindings.json').read_text()).values()]
run('http-evaluation', [sys.executable, here.parent / 'evaluation_inventory.py', aspnet, out / 'http-evaluation.json', *sorted(set(http_projects))])
run('bootstrap', [sys.executable, here / 'objectpool.py', aspnet, prior / 'objectpool-inventory.json', out / 'bootstrap', prior / 'vstest.nupkg'])
run('http-mapping', [sys.executable, here / 'http.py', out / 'http', out / 'http-evaluation.json', out / 'bootstrap/workspace'])
work = out / 'http/upstream'; base = out / 'http-base'
startup = [bazel, '--output_base=' + str(base), '--ignore_all_rc_files']
run('http-sync', startup + ['run', '//:sync', '--jobs=2'], work)
p = work / 'BUILD.bazel'; p.write_text('load(":projects.generated.bzl","app_projects")\n' + p.read_text() + '\napp_projects()\n')
run('http-controls', [sys.executable, here / 'controls.py', work, base, out / 'http-raw/results.trx', out / 'http-controls', '//:src_Http_Http.Abstractions_test_Microsoft.AspNetCore.Http.Abstractions.Tests_net10_0', 'src/Http/Http.Abstractions/src/QueryString.cs', 'return ToUriComponent();', 'GC.KeepAlive(typeof(QueryString)); return ToUriComponent();', 'src_Http_Http.Abstractions_src_Microsoft.AspNetCore.Http.Abstractions_net10_0'])
run('http-graph-controls', [sys.executable, here / 'http_graph_controls.py', work, base, out / 'http-graph-controls'])
run('http-shutdown', startup + ['shutdown'], work)
assembly = 'System.Collections.Immutable'
library = 'src/libraries/' + assembly + '/src/' + assembly + '.csproj'
tests = 'src/libraries/' + assembly + '/tests/' + assembly + '.Tests.csproj'
run('immutable-raw-build', [dotnet, 'build', runtime / tests, '-c', 'Release', '-p:TargetFramework=net10.0', '-p:TargetArchitecture=arm64', '-p:TargetOS=linux', '-p:UseLocalTargetingRuntimePack=false', '-p:RestoreUseStaticGraphEvaluation=false', '-p:NuGetAudit=false', '-p:UseSharedCompilation=false', '-p:NetCoreSdkRoot=' + str(sdk / 'sdk/10.0.400')])
run('immutable-raw-tests', [sys.executable, here / 'runtime_raw.py', runtime, out / 'immutable-raw', prior / 'vstest.nupkg', assembly])
probe = inventory_tool('immutable', 'runtime', runtime, tests)
run('immutable-evaluation', [sys.executable, here.parent / 'evaluation_inventory.py', runtime, out / 'immutable-evaluation.json', library, tests], env=dict(os.environ, RULES_MSBUILD_INVENTORY_PROPERTIES='{"TargetArchitecture":"arm64","TargetOS":"linux","UseLocalTargetingRuntimePack":"false"}'))
run('immutable-mapping', [sys.executable, here / 'runtime.py', out / 'immutable', probe / 'inventory.json', out / 'immutable-evaluation.json', 'linux'])
work = out / 'immutable/upstream'; base = out / 'immutable-base'
startup = [bazel, '--output_base=' + str(base), '--ignore_all_rc_files']
run('immutable-sync', startup + ['run', '//:sync', '--jobs=2'], work)
run('immutable-host', [sys.executable, here / 'runtime_host.py', work, assembly])
run('immutable-controls', [sys.executable, here / 'controls.py', work, base, out / 'immutable-raw/results/results.trx', out / 'immutable-controls', '//:src_libraries_System.Collections.Immutable_tests_System.Collections.Immutable.Tests_net10_0', 'src/libraries/System.Collections.Immutable/src/Validation/Requires.cs', 'throw new ArgumentNullException(parameterName);', 'GC.KeepAlive(typeof(Requires)); throw new ArgumentNullException(parameterName);', 'src_libraries_System.Collections.Immutable_ref_System.Collections.Immutable_net10.0', assembly])
run('immutable-shutdown', startup + ['shutdown'], work)
