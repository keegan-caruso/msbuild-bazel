"""Exercise explicit build IDs and timestamp diagnostics with actual MSBuild.

No SDK imports, restore, compiler, cache publication or preparation reuse is used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

from check_msbuild_time import scan


PROJECT = '''<Project>
  <Import Project="Version.props" />
  <ItemGroup><Compile Include="Program.cs" /></ItemGroup>
  <Target Name="Build">
    <PropertyGroup><ObservedTimestamp>@(Compile->'%(ModifiedTime)')</ObservedTimestamp></PropertyGroup>
    <WriteLinesToFile File="version.txt" Lines="$(Version)" Overwrite="true" />
  </Target>
</Project>
'''
VERSION = '''<Project>
  <PropertyGroup>
    <_BuildNumber>$(OfficialBuildId)</_BuildNumber>
    <_BuildNumber Condition="'$(OfficialBuildId)' == ''">$([System.DateTime]::Now.ToString(yyyyMMdd)).1</_BuildNumber>
    <Version>1.2.3-alpha.$(_BuildNumber)</Version>
  </PropertyGroup>
</Project>
'''


def probe(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, DOTNET_CLI_HOME=str(output / 'home'), DOTNET_NOLOGO='1',
                       DOTNET_CLI_TELEMETRY_OPTOUT='1', MSBUILDDISABLENODEREUSE='1')
    dotnet = ['bash', str(repo / 'scripts/dotnet.sh')]
    sdk = subprocess.check_output(dotnet + ['--version'], env=environment, text=True).strip()
    report = dict(schemaVersion=1, sdkVersion=sdk, platform=platform.platform(), accepted=False,
                  scope='msbuild-evaluation-and-target-time-inputs', reuseEnabled=False,
                  eligibility='not-established', cases={})
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(name, build_id, timestamp=946684800):
        workspace = output / name
        workspace.mkdir()
        inputs = {'Build.proj': PROJECT, 'Version.props': VERSION,
                  'Program.cs': 'class App { static System.DateTime Clock() => System.DateTime.Now; }\n'}
        for filename, content in inputs.items():
            (workspace / filename).write_text(content)
            os.utime(workspace / filename, (timestamp, timestamp))
        properties = {} if build_id is None else {'OfficialBuildId': build_id}
        # This is only an experimental declared-input fingerprint. It is NOT a
        # complete production identity or proof that the workload is eligible.
        fingerprint = hashlib.sha256(json.dumps(dict(files=inputs, properties=properties, sdk=sdk), sort_keys=True).encode()).hexdigest()
        args = dotnet + ['msbuild', str(workspace / 'Build.proj'), '-nologo', '-nodeReuse:false',
                         '-target:Build', '-getProperty:Version,ObservedTimestamp']
        args += ['-property:' + key + '=' + value for key, value in properties.items()]
        result = subprocess.run(args, cwd=workspace, env=environment, capture_output=True, text=True)
        (workspace / 'msbuild.log').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError('MSBuild failed: ' + str(workspace / 'msbuild.log'))
        observation = json.loads(result.stdout[result.stdout.index('{'):])['Properties']
        diagnostics = scan([workspace / 'Build.proj'])
        (workspace / 'diagnostics.json').write_text(json.dumps(diagnostics, indent=2) + '\n')
        if diagnostics['errors']:
            raise AssertionError(diagnostics['errors'])
        case = dict(properties=properties, experimentalInputFingerprint=fingerprint,
                    observation=observation, artifact=(workspace / 'version.txt').read_text(),
                    rules=[finding['rule'] for finding in diagnostics['findings']])
        report['cases'][name] = case
        return case

    first = run('fixed', '20260907.1')
    repeated = run('fresh-workspace', '20260907.1')
    assert first == repeated
    assert first['observation']['Version'] == '1.2.3-alpha.20260907.1'
    assert set(first['rules']) == {'wall-clock', 'item-timestamp'}
    changed = run('changed-build-id', '20260908.2')
    assert changed['experimentalInputFingerprint'] != first['experimentalInputFingerprint']
    assert changed['artifact'] != first['artifact']
    touched = run('timestamp-only', '20260907.1', 946684810)
    assert touched['experimentalInputFingerprint'] == first['experimentalInputFingerprint']
    assert touched['observation']['ObservedTimestamp'] != first['observation']['ObservedTimestamp']
    assert touched['artifact'] == first['artifact']
    fallback = run('clock-fallback', None)
    assert fallback['observation']['Version'].startswith('1.2.3-alpha.')
    assert 'wall-clock' in fallback['rules']
    report['accepted'] = True
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    probe(parser.parse_args().output)
