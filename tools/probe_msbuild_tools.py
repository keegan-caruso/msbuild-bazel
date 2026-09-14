"""Qualify explicit tool-framework and reference-engine inputs on native .NET 11.

Consumes the assembled SDK/engine matrix configuration and toolsets. All owned
sources are copied; each input combination has separate restore/build outputs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import msbuild_tool

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--matrix-config', type=Path, required=True)
p.add_argument('--toolsets', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
config = json.loads(a.matrix_config.read_text())
root = a.output.resolve()
root.mkdir(parents=True, exist_ok=False)
sdk = config['sdks']['sdk11']
host = config['hosts']['host11']
compiler = a.toolsets.resolve() / 'sdk11-ms1810/sdk' / sdk['version'] / 'MSBuild.dll'
prefix = [str(Path(host['root']) / 'dotnet'), 'exec', '--fx-version', host['runtime'], str(compiler)]
report = {'cases': {}, 'passed': False}


def run(label, command, cwd, environment):
    result = subprocess.run(command, cwd=cwd, env=environment, text=True, capture_output=True, timeout=180)
    (root / (label + '.log')).write_text(result.stdout + result.stderr)
    return result


names = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '--cached', '--others', '--exclude-standard', 'tools', '.editorconfig'], text=True).splitlines()
for engine, framework in [('ms189', 'net10.0'), ('ms189', 'net11.0'), ('ms1810', 'net11.0'), ('ms1810', 'net10.0')]:
    label = engine + '-' + framework
    snapshot = root / label
    snapshot.mkdir()
    for name in names:
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    (snapshot / 'global.json').write_text(json.dumps({'sdk': {'version': sdk['version'], 'rollForward': 'disable', 'allowPrerelease': True}}))
    (snapshot / 'NuGet.Config').write_text('<configuration><packageSources><clear/><add key="nuget" value="https://api.nuget.org/v3/index.json" /></packageSources></configuration>')
    engine_sdk = config['sdks']['sdk10'] if engine == 'ms189' else sdk
    engine_root = a.toolsets.resolve() / ('sdk10-' + engine if engine == 'ms189' else 'sdk11-' + engine) / 'sdk' / engine_sdk['version']
    env = dict(os.environ, DOTNET_ROOT=host['root'], DOTNET_HOST_PATH=str(Path(host['root']) / 'dotnet'), DOTNET_CLI_HOME=str(root / 'home'), NUGET_PACKAGES=str(root / 'packages'), DOTNET_CLI_TELEMETRY_OPTOUT='1', MSBUILDUSESERVER='0', PWD=str(snapshot), MSBuildSDKsPath=str(Path(sdk['root']) / 'sdk' / sdk['version'] / 'Sdks'))
    for tool in ['GraphExport', 'ReplayPlugin']:
        key = label + '-' + tool
        command = prefix + msbuild_tool.build_arguments(snapshot / 'tools' / tool, framework, engine_root)[1:]
        result = run(key, command, snapshot, env)
        expected_failure = engine == 'ms1810' and framework == 'net10.0'
        case = {'command': command, 'returncode': result.returncode, 'framework': framework, 'engineRoot': str(engine_root)}
        if expected_failure:
            case['passed'] = result.returncode != 0 and 'CS1705' in result.stdout + result.stderr
        else:
            case['passed'] = result.returncode == 0
            if case['passed']:
                artifact = msbuild_tool.output_path(result.stdout, tool)
                case['artifact'] = str(artifact)
                if tool == 'GraphExport':
                    copied = artifact.parent / 'Microsoft.Build.dll'
                    case['engineAssemblySha256'] = hashlib.sha256(copied.read_bytes()).hexdigest()
                    case['passed'] = case['engineAssemblySha256'] == hashlib.sha256((engine_root / 'Microsoft.Build.dll').read_bytes()).hexdigest()
                    load_command = [str(Path(host['root']) / 'dotnet'), 'exec', '--fx-version', host['runtime'], str(artifact), '--request', str(snapshot / 'absent.json')]
                    loaded = run(key + '-load', load_command, snapshot, env)
                    case['loadReturncode'] = loaded.returncode
                    case['passed'] = case['passed'] and loaded.returncode == 2 and 'invalid-request:' in loaded.stderr
        report['cases'][key] = case
        (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(key, case['passed'], flush=True)
snapshot = root / 'ms1810-net11.0'
project = snapshot / 'tools/ReplayPlugin'
engine_root = a.toolsets.resolve() / 'sdk11-ms1810/sdk' / sdk['version']
for name, arguments, diagnostic in [
    ('missing-engine', msbuild_tool.build_arguments(project, 'net11.0', snapshot / 'missing-engine'), 'must contain the selected MSBuild engine assemblies'),
    ('framework-mismatch', msbuild_tool.build_arguments(project, 'net11.0', engine_root) + ['-property:TargetFramework=net10.0'], 'TargetFramework must match the explicit'),
]:
    command = prefix + arguments[1:]
    result = run(name, command, snapshot, env)
    report['cases'][name] = {'command': command, 'returncode': result.returncode, 'passed': result.returncode != 0 and diagnostic in result.stdout + result.stderr}
report['passed'] = all(case['passed'] for case in report['cases'].values())
(root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
raise SystemExit(0 if report['passed'] else 1)
