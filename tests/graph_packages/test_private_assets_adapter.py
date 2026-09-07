"""Generated adapter parity with the measured ordinary PrivateAssets baseline."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from graph_private_assets import probe
from prepare_graph import DOTNET_ROOT, prepare
from probe_graph_execution import BAZEL
from probe_bazel import json_stream


class PrivateAssetsAdapter(unittest.TestCase):
    def test_matches_ordinary_compile_visibility_and_runtime_copy(self):
        evidence = Path(tempfile.mkdtemp(prefix='graph-private-adapter-')).resolve()
        ordinary = probe(evidence / 'ordinary')
        dotnet = DOTNET_ROOT / 'dotnet'
        strategy = 'darwin-sandbox' if platform.system() == 'Darwin' else 'linux-sandbox'
        report = dict(schemaVersion=1, cases={})

        def run(name, command, cwd, success=True):
            environment_root = evidence / 'bootstrap' if cwd == ROOT else cwd
            environment = dict(os.environ, DOTNET_CLI_HOME=str(environment_root / '.dotnet-home'),
                NUGET_PACKAGES=str(environment_root / '.nuget/packages'), MSBUILDDISABLENODEREUSE='1')
            result = subprocess.run([str(a) for a in command], cwd=cwd, env=environment,
                capture_output=True, text=True, timeout=240)
            (evidence / (name + '.log')).write_text(result.stdout + result.stderr)
            if success:
                self.assertEqual(result.returncode, 0, result.stdout[-5000:] + result.stderr[-5000:] + '\nEvidence: ' + str(evidence))
            return result

        run('exporter-build', [dotnet, 'build', ROOT / 'tools/GraphExport', '-c', 'Release', '--nologo'], ROOT)
        for mode, expected in ordinary['cases'].items():
            with self.subTest(private_assets=mode):
                workspace = evidence / 'ordinary' / mode
                program = workspace / 'src/App/Program.cs'
                program.write_text('Console.WriteLine(Left.Value.Text + "|" + Right.Value.Text);\n')
                case = {}
                for phase in ('baseline', 'direct'):
                    if phase == 'direct':
                        program.write_text(program.read_text() + 'Console.WriteLine(RulesMsbuild.Binary.Value.Read());\n')
                    prefix = mode + '-' + phase
                    manifest = evidence / (prefix + '-graph.json')
                    request = evidence / (prefix + '-export.json')
                    request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(workspace),
                        dotnetRoot=str(DOTNET_ROOT), sdkVersion='10.0.100',
                        packageRoot=str(workspace / '.nuget/packages'),
                        entryPoints=[dict(project='build.proj', globalProperties={'Configuration':'Release'})],
                        output=str(manifest))))
                    run(prefix + '-export', [dotnet, ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], workspace)
                    generated = evidence / (prefix + '-generated')
                    graph = prepare(workspace, manifest, generated)
                    nodes = {n['id']: Path(n['project']).stem for n in graph['nodes']}
                    app = next(identity for identity, name in nodes.items() if name == 'App')
                    manifests = {}
                    for identity, name in nodes.items():
                        package_manifest = json.loads((generated / 'package-manifests' / (identity + '.json')).read_text())
                        manifests[name] = sorted(p['id'] + '/' + p['version'] for p in package_manifest['packages'])
                        self.assertEqual(manifests[name], expected['nodes'][name]['packages'])
                    execution = evidence / (prefix + '-execution.json')
                    result = run(prefix + '-build', [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc',
                        '--output_base=' + str(evidence / (prefix + '-base')),
                        '--output_user_root=' + str(evidence / 'bazel-user'),
                        'build', '//:all', '--disk_cache=' + str(evidence / (mode + '-cache')),
                        '--spawn_strategy=' + strategy, '--strategy=MsbuildProject=' + strategy,
                        '--jobs=2', '--noshow_progress', '--execution_log_json_file=' + str(execution)],
                        generated, success=not (mode == 'all' and phase == 'direct'))
                    actions = [r for r in json_stream(execution) if r.get('mnemonic') == 'MsbuildProject']
                    executed = []
                    for action in actions:
                        identity = action['targetLabel'].split(':node_')[-1]
                        if not action.get('cacheHit', False):
                            self.assertEqual(action.get('runner'), strategy)
                            executed.append(nodes[identity])
                        if result.returncode == 0 and not action.get('cacheHit', False):
                            diagnostic = json.loads((generated / f'bazel-bin/node_{identity}.diagnostics/action.json').read_text())
                            self.assertEqual(diagnostic['compiledProjects'], [nodes[identity]])
                    self.assertEqual(sorted(executed), ['App', 'Left', 'Right', 'Shared'] if phase == 'baseline' else ['App'])
                    case[phase] = dict(packageManifests=manifests, returncode=result.returncode, executedProjects=sorted(executed))
                    if phase == 'direct':
                        self.assertEqual(result.returncode == 0, expected['appDirectPackageCompileReturncode'] == 0)
                        if mode == 'all':
                            self.assertIn('CS0103', result.stdout + result.stderr)
                            self.assertFalse((generated / f'bazel-bin/node_{app}.bundle/bundle.json').exists())
                        continue
                    app_output = generated / f'bazel-bin/node_{app}.bundle/artifacts/src/App/bin/Release/net10.0'
                    self.assertEqual(sorted(p.name for p in app_output.iterdir() if p.is_file()), expected['nodes']['App']['outputFiles'])
                    for assembly, copied in expected['packageCopies'].items():
                        path = app_output / assembly
                        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
                        self.assertEqual(digest, copied['outputSha256'])
                    isolated = evidence / (mode + '-isolated-runtime')
                    shutil.copytree(app_output, isolated)
                    runtime = run(prefix + '-runtime', [dotnet, isolated / 'App.dll'], isolated, success=False)
                    case[phase].update(runtimeReturncode=runtime.returncode, runtimeOutput=runtime.stdout.strip())
                    self.assertEqual(runtime.returncode == 0, expected['runtimeReturncode'] == 0)
                    self.assertEqual(runtime.stdout.strip(), expected['runtimeOutput'])
                    if mode == 'all':
                        self.assertIn('FileNotFoundException', runtime.stderr)
                        self.assertIn('RulesMsbuild.Binary', runtime.stderr)
                report['cases'][mode] = case
                (evidence / 'adapter-report.json').write_text(json.dumps(report, indent=2))
        print('PrivateAssets adapter evidence: ' + str(evidence), flush=True)


if __name__ == '__main__':
    unittest.main()
