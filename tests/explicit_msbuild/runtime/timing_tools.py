"""Fail closed on benchmark tool versions before touching build state."""
import hashlib
import os
from pathlib import Path
import subprocess


def verify_tools(expected_bazel=None, cwd=None):
    sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
    sdk_version = subprocess.check_output([sdk/'dotnet', '--version'], cwd=cwd, text=True).strip()
    if sdk_version != '10.0.400':
        raise RuntimeError(f'Expected SDK 10.0.400; selected {sdk_version} at {sdk}')
    result = dict(sdkVersion=sdk_version, sdkRoot=str(sdk))
    if expected_bazel is not None:
        bazel = Path(os.environ['RULES_MSBUILD_BAZEL']).resolve()
        version = subprocess.check_output(
            [bazel, '--batch', '--ignore_all_rc_files', 'version', '--gnu_format'],
            cwd=cwd, text=True).strip()
        if version != 'bazel '+expected_bazel:
            raise RuntimeError(f'Expected Bazel {expected_bazel}; selected {version} at {bazel}')
        result.update(bazelVersion=expected_bazel, bazelExecutable=str(bazel),
                      bazelSha256=hashlib.sha256(bazel.read_bytes()).hexdigest())
    return result
