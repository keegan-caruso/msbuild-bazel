"""Host commands and explicit platform choices for disposable graph fixtures."""
from contextlib import contextmanager
import json
import ntpath
import os
import platform
import tempfile
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


def bazel_environment(**overrides):
    environment = dict(os.environ, **overrides)
    # Native Bazelisk runs from disposable workspaces without this repo's pin.
    environment['USE_BAZEL_VERSION'] = environment.get('USE_BAZEL_VERSION') or (ROOT / '.bazelversion').read_text().strip()
    return environment


def sdk_declaration(name='dotnet', *, global_json=None, version=None):
    if (global_json is None) == (version is None):
        raise ValueError('Choose one SDK version or global.json')
    attributes = {'name': name, 'global_json' if global_json is not None else 'version': global_json if global_json is not None else version}
    if WINDOWS:
        # Windows support is opt-in; do not change the extension's release defaults.
        architecture = platform.machine().lower()
        platforms = {'amd64': 'win-x64', 'x86_64': 'win-x64', 'arm64': 'win-arm64', 'aarch64': 'win-arm64'}
        if architecture not in platforms:
            raise ValueError('Unsupported Windows fixture architecture: ' + architecture)
        attributes['platforms'] = [platforms[architecture]]
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


def _cleanup_path(path):
    if not WINDOWS:
        return path
    absolute = ntpath.abspath(path)
    if absolute.startswith('\\\\?\\'):
        return absolute
    return '\\\\?\\UNC\\' + absolute[2:] if absolute.startswith('\\\\') else '\\\\?\\' + absolute


@contextmanager
def temporary_directory(*, prefix):
    """Keep ordinary fixture paths; delete owned Windows trees without MAX_PATH."""
    temporary = tempfile.TemporaryDirectory(prefix=prefix)
    try:
        yield temporary.name
    finally:
        # TemporaryDirectory performs its usual read-only/error handling. Only
        # its deletion path changes; Bazel and MSBuild never receive this form.
        temporary.name = _cleanup_path(temporary.name)
        temporary.cleanup()
