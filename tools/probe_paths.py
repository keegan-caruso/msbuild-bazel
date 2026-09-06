"""Measure raw MSBuild cache handoff across paths; retain all evidence.

This deliberately bypasses the v1 driver's workspace guard only for the raw
relocation probe. It does not change the supported dependency contract.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DOTNET = Path(os.environ.get('SPIKE_DOTNET_ROOT', ROOT / '.tools/dotnet')) / 'dotnet'


def probe(directory):
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    workspace = directory / 'producer-workspace'
    shutil.copytree(ROOT / 'tests/fixtures/two-projects', workspace)

    def driver(name, operation, project=None, dependencies=()):
        output = directory / name
        request = dict(schemaVersion=1, operation=operation, workspace=str(workspace),
                       output=str(output), configuration='Release')
        if project:
            request.update(project=project, dependencies=[str(p) for p in dependencies])
        request_file = directory / f'{name}.request.json'
        request_file.write_text(json.dumps(request, indent=2) + '\n')
        process = subprocess.run(
            [sys.executable, str(ROOT / 'tools/spike.py'), '--request', str(request_file)],
            text=True, capture_output=True, timeout=180,
        )
        (directory / f'{name}.driver.log').write_text(process.stdout + process.stderr)
        if process.returncode:
            raise RuntimeError(f'{name} failed; inspect {directory}')
        return output

    def clean():
        for project in ('Shared', 'App'):
            for folder in ('bin', 'obj'):
                shutil.rmtree(workspace / project / folder, ignore_errors=True)

    def observe(output, returncode=0):
        log = (output / 'build.log').read_text()
        result = dict(returncode=returncode,
                      compiledProjects=[p for p in ('Shared', 'App')
                                        if f'SPIKE_COMPILE:{p}' in log],
                      log=str(output / 'build.log'))
        if returncode == 0:
            process = subprocess.run(
                [str(DOTNET), str(workspace / 'App/bin/Release/net10.0/App.dll')],
                text=True, capture_output=True, timeout=30,
            )
            (output / 'application.log').write_text(process.stdout + process.stderr)
            result.update(applicationReturncode=process.returncode,
                          applicationOutput=process.stdout.strip())
        return result

    driver('restore-producer', 'restore')
    app_restore = directory / 'app-restore'
    shutil.copytree(workspace / 'App/obj', app_restore)
    original_bundle = driver('original-bundle', 'project', 'Shared')
    moved_bundle = directory / 'different-action-output' / 'shared-bundle'
    moved_bundle.parent.mkdir()
    shutil.move(original_bundle, moved_bundle)
    clean()
    shutil.copytree(app_restore, workspace / 'App/obj')
    same_path = driver('same-workspace', 'project', 'App', [moved_bundle])
    report = dict(schemaVersion=1, platform=platform.platform(), dotnet=str(DOTNET),
                  movedBundle=observe(same_path))

    # Remove the producer path, including NuGet/restore state. Restore afresh at
    # the consumer path so stale App assets cannot masquerade as cache failure.
    shutil.rmtree(workspace)
    workspace = directory / 'consumer-workspace'
    shutil.copytree(ROOT / 'tests/fixtures/two-projects', workspace)
    driver('restore-consumer', 'restore')
    manifest = json.loads((moved_bundle / 'result.json').read_text())
    for relative in manifest['artifacts']:
        destination = workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(moved_bundle / 'artifacts' / relative, destination)

    output = directory / 'raw-relocation'
    output.mkdir()
    command = [str(DOTNET), 'msbuild', 'App/App.csproj', '-p:Configuration=Release',
               '-t:Build', '-isolateProjects',
               f'-inputResultsCaches:{moved_bundle / "results.cache"}',
               f'-outputResultsCache:{output / "results.cache"}',
               '-nologo', '-verbosity:normal', '-nodeReuse:false']
    (output / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
    environment = os.environ.copy()
    environment.update(DOTNET_ROOT=str(DOTNET.parent),
                       DOTNET_CLI_HOME=str(workspace / '.dotnet-home'),
                       NUGET_PACKAGES=str(workspace / '.nuget/packages'),
                       DOTNET_NOLOGO='1', DOTNET_CLI_TELEMETRY_OPTOUT='1',
                       MSBUILDDISABLENODEREUSE='1')
    process = subprocess.run(command, cwd=workspace, env=environment,
                             text=True, capture_output=True, timeout=150)
    (output / 'build.log').write_text(process.stdout + process.stderr)
    report['relocatedWorkspace'] = observe(output, process.returncode)

    # A fresh dependency cache at this path is a positive control for the same
    # consumer/toolchain. It rules out a generally broken relocated checkout.
    clean()
    driver('restore-control', 'restore')
    fresh_shared = driver('fresh-shared', 'project', 'Shared')
    shutil.rmtree(workspace / 'Shared/bin')
    shutil.rmtree(workspace / 'Shared/obj')
    fresh_app = driver('fresh-app', 'project', 'App', [fresh_shared])
    report['freshCacheControl'] = observe(fresh_app)
    (directory / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path,
                        help='New directory for copied workspaces, logs and report.json')
    arguments = parser.parse_args()
    try:
        print(json.dumps(probe(arguments.output), indent=2))
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
