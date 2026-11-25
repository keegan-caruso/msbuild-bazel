"""Host commands and explicit platform choices for disposable graph fixtures."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WINDOWS = os.name == 'nt'


def bazel_startup(*arguments):
    executable = os.environ.get('RULES_MSBUILD_BAZEL')
    if not executable:
        executable = os.environ.get('RULES_MSBUILD_BAZELISK', str(ROOT / '.tools/bin/bazelisk.exe')) if WINDOWS else str(ROOT / 'scripts/bazel-launcher.sh')
    command = [executable]
    if WINDOWS and Path(executable).suffix.lower() == '.sh':
        bash = os.environ.get('RULES_MSBUILD_BASH')
        if not bash:
            raise ValueError('Set RULES_MSBUILD_BAZEL to the native pinned executable, or set RULES_MSBUILD_BASH for a shell launcher')
        command.insert(0, bash)
    return command + [str(argument) for argument in arguments]


def sdk_declaration(name='dotnet', *, global_json=None, version=None):
    if (global_json is None) == (version is None):
        raise ValueError('Choose one SDK version or global.json')
    attributes = {'name': name, 'global_json' if global_json is not None else 'version': global_json if global_json is not None else version}
    if WINDOWS:
        # Windows support is opt-in; do not change the extension's release defaults.
        attributes['platforms'] = ['win-x64']
    return 'dotnet.sdk(' + ','.join(key + '=' + json.dumps(value) for key, value in attributes.items()) + ')\n'


def assert_no_host_paths(value, *roots):
    """Inspect decoded report strings so Windows JSON escaping cannot hide a leak."""
    prefixes = [str(root).replace('\\', '/') for root in roots]
    def inspect(item):
        if isinstance(item, dict):
            for key, value in item.items():
                inspect(key)
                inspect(value)
        elif isinstance(item, (list, tuple)):
            for value in item:
                inspect(value)
        elif isinstance(item, str):
            text = item.replace('\\', '/')
            for prefix in prefixes:
                assert (prefix.casefold() not in text.casefold() if WINDOWS else prefix not in text), item
    inspect(value)
