"""Milestone-one MSBuild process boundary. Not a Bazel rule or portable cache."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DOTNET = Path(os.environ.get('SPIKE_DOTNET_ROOT', ROOT / '.tools/dotnet')) / 'dotnet'
SDK = '10.0.100'
FRAMEWORK = 'net10.0'


def invoke(arguments, workspace, output):
    environment = os.environ.copy()
    environment.update(
        DOTNET_ROOT=str(DOTNET.parent),
        DOTNET_CLI_HOME=str(workspace / '.dotnet-home'),
        NUGET_PACKAGES=str(workspace / '.nuget/packages'),
        DOTNET_NOLOGO='1', DOTNET_CLI_TELEMETRY_OPTOUT='1',
        MSBUILDDISABLENODEREUSE='1',
    )
    process = subprocess.run(
        [str(DOTNET), 'msbuild', *arguments, '-nologo', '-verbosity:normal', '-nodeReuse:false'],
        cwd=workspace, env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=150,
    )
    (output / 'build.log').write_text(process.stdout)
    if process.returncode:
        raise RuntimeError(f'MSBuild exited {process.returncode}; see {output / "build.log"}')


def stage_dependency(directory, workspace, configuration):
    try:
        result = json.loads((directory / 'result.json').read_text())
        expected = {
            'schemaVersion': 1, 'operation': 'project', 'project': 'Shared',
            'workspace': str(workspace), 'configuration': configuration,
            'targetFramework': FRAMEWORK, 'sdkVersion': SDK,
        }
        for key, value in expected.items():
            if result.get(key) != value:
                raise ValueError(f'dependency {key} mismatch: expected {value!r}')
        cache = directory / 'results.cache'
        if result.get('resultsCache') != 'results.cache' or not cache.is_file():
            raise ValueError('dependency results cache missing')
        artifacts = result['artifacts']
        if not artifacts:
            raise ValueError('dependency artifacts are empty')
        # Validate the entire bundle before copying anything.
        for relative in artifacts:
            path = Path(relative)
            if path.is_absolute() or '..' in path.parts or path.parts[:2] not in [('Shared', 'bin'), ('Shared', 'obj')]:
                raise ValueError(f'invalid dependency artifact path: {relative}')
            if not (directory / 'artifacts' / path).is_file():
                raise ValueError(f'dependency artifact missing: {relative}')
        for relative in artifacts:
            destination = workspace / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(directory / 'artifacts' / relative, destination)
        return cache
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f'invalid dependency bundle: {error}') from error


def execute(request):
    if request.get('schemaVersion') != 1:
        raise ValueError('schemaVersion must be 1')
    operation = request['operation']
    if operation not in ('restore', 'baseline', 'project'):
        raise ValueError('unsupported operation')
    workspace = Path(request['workspace'])
    output = Path(request['output'])
    if not workspace.is_absolute() or not output.is_absolute():
        raise ValueError('workspace and output must be absolute paths')
    workspace = workspace.resolve(strict=True)
    output = output.resolve()
    if output == workspace or workspace in output.parents:
        raise ValueError('output must be outside workspace')
    if workspace == ROOT / 'tests/fixtures/two-projects':
        raise ValueError('copy the fixture to an isolated workspace first')
    if request.get('configuration') != 'Release':
        raise ValueError('only Release configuration is supported')
    configuration = request['configuration']
    output.mkdir(parents=True, exist_ok=False)
    arguments = ['-p:Configuration=Release']
    project = None
    if operation == 'restore':
        arguments += ['dirs.proj', '-t:Restore']
    elif operation == 'baseline':
        arguments += ['dirs.proj', '-t:Build', '-graphBuild', '-isolateProjects']
    else:
        project = request.get('project')
        dependencies = request.get('dependencies', [])
        if project not in ('Shared', 'App'):
            raise ValueError('project must be Shared or App')
        if len(dependencies) != (1 if project == 'App' else 0):
            raise ValueError('App requires one Shared dependency; Shared requires none')
        for directory in dependencies:
            cache = stage_dependency(Path(directory), workspace, configuration)
            arguments += [f'-inputResultsCaches:{cache}']
        targets = 'Build'
        if project == 'Shared':
            # Fixed fixture protocol; a future graph planner must derive target requests.
            targets = 'GetTargetFrameworks;Build;GetTargetPath;GetNativeManifest;GetCopyToOutputDirectoryItems;GetTargetPathWithTargetPlatformMoniker'
        arguments += [f'{project}/{project}.csproj', f'-t:{targets}',
                      '-isolateProjects', f'-outputResultsCache:{output / "results.cache"}']
    invoke(arguments, workspace, output)
    artifacts = []
    if operation == 'project':
        for folder in ('bin', 'obj'):
            for source in sorted((workspace / project / folder).rglob('*')):
                if source.is_file():
                    relative = source.relative_to(workspace)
                    destination = output / 'artifacts' / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    artifacts.append(relative.as_posix())
    result = {
        'schemaVersion': 1, 'operation': operation, 'project': project,
        'workspace': str(workspace), 'configuration': configuration,
        'targetFramework': FRAMEWORK, 'sdkVersion': SDK, 'artifacts': artifacts,
        'resultsCache': 'results.cache' if operation == 'project' else None,
    }
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True, type=Path)
    arguments = parser.parse_args()
    try:
        execute(json.loads(arguments.request.read_text()))
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
