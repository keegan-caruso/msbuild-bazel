"""Read MSBuild-reported adapter tool outputs instead of assuming a tool TFM."""
import json
from pathlib import Path


def build_arguments(project, framework=None, engine_root=None):
    arguments = ['msbuild', str(project), '-restore', '-target:Build',
                 '-property:Configuration=Release', '-nologo',
                 '-getProperty:TargetPath,TargetFramework,RulesMSBuildEngineRoot']
    if framework is not None:
        if framework not in ('net10.0', 'net11.0'):
            raise ValueError('unsupported tool target framework: ' + framework)
        arguments.append('-property:RulesMSBuildToolTargetFramework=' + framework)
    if engine_root is not None:
        arguments.append('-property:RulesMSBuildEngineRoot=' + str(Path(engine_root).resolve()))
    return arguments


def output_path(stdout, tool):
    # With -getProperty and a target, MSBuild writes its result JSON after build
    # diagnostics. Parse the final JSON object, never a stale conventional path.
    start = stdout.rfind('\n{')
    data = json.loads(stdout[start + 1:] if start >= 0 else stdout)
    properties = data['Properties']
    if properties['TargetFramework'] not in ('net10.0', 'net11.0'):
        raise ValueError('unsupported built tool framework')
    path = Path(properties['TargetPath'])
    if not path.is_absolute() or path.name != tool + '.dll' or not path.is_file():
        raise ValueError('missing or invalid built tool output: ' + str(path))
    return path
