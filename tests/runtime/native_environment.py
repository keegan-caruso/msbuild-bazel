"""Selected distribution/compiler boundary inside declared native tool roots."""

import json
from pathlib import Path
import re

DISTRIBUTION = 'ubuntu/26.04'
LLVM_MAJOR = 18
LLVM_VERSION = '18.1.8'


def load_catalog(architecture='arm64', sdk=False):
    if architecture not in ('arm64', 'x64'):
        raise ValueError('Unsupported native runtime architecture: ' + architecture)
    filename = 'native-packages-x64.json' if architecture == 'x64' else 'native-packages.json'
    if sdk:
        if architecture != 'x64':
            raise ValueError('Declared SDK package catalog currently requires x64')
        filename = 'native-packages-sdk-x64.json'
    value = json.loads((Path(__file__).parent / filename).read_text())
    if value['platform'] != 'linux-' + architecture or value['distribution'] != 'ubuntu-26.04':
        raise ValueError('Native package catalog platform/distribution differs')
    packages = value['packages']
    names = [package['name'] for package in packages]
    if not packages or len(set(names)) != len(names) or not set(value['roots']) <= set(names):
        raise ValueError('Native package catalog has missing or duplicate packages')
    deb_architecture = 'amd64' if architecture == 'x64' else 'arm64'
    for package in packages:
        if package['architecture'] not in (deb_architecture, 'all'):
            raise ValueError('Native package architecture differs: ' + package['name'])
        if not re.fullmatch(r'[a-f0-9]{64}', package['sha256']):
            raise ValueError('Native package SHA-256 is invalid: ' + package['name'])
        if not package['url'].startswith('https://archive.ubuntu.com/ubuntu/pool/') or not package['url'].endswith('_' + package['architecture'] + '.deb'):
            raise ValueError('Native package URL is not the official Ubuntu archive')
    compiler_packages = ['clang-18', 'lld-18', 'llvm-18', 'libclang-rt-18-dev']
    if sdk:
        compiler_packages += ['lldb-18', 'liblldb-18', 'liblldb-18-dev', 'python3-lldb-18']
    if not set(compiler_packages) <= set(names):
        raise ValueError('Native package catalog omits selected LLVM tools')
    for name in compiler_packages:
        if next(package for package in packages if package['name'] == name)['version'] != '1:18.1.8-20ubuntu8':
            raise ValueError('Native LLVM package pin differs: ' + name)
    return value


def build_prefix(architecture='arm64'):
    if architecture not in ('arm64', 'x64'):
        raise ValueError('Unsupported native runtime architecture: ' + architecture)
    machine = 'aarch64' if architecture == 'arm64' else 'x86_64'
    target = 'aarch64' if architecture == 'arm64' else 'x86_64'

    # Check the mounted declared root, rather than the container that assembled it.
    return ('set -euo pipefail\n'
            f'export PATH=/usr/lib/llvm-{LLVM_MAJOR}/bin:$PATH\n'
            f'export CC=clang-{LLVM_MAJOR} CXX=clang++-{LLVM_MAJOR}\n'
            '. /etc/os-release\n'
            f'test "$ID/$VERSION_ID" = {DISTRIBUTION}\n'
            f'test "$(uname -m)" = {machine}\n'
            f'clang-{LLVM_MAJOR} -dumpmachine | grep -E "^{target}-.*linux-gnu$"\n'
            f'clang-{LLVM_MAJOR} --version | grep -F "clang version {LLVM_VERSION}"\n')


def sdk_account_check():
    """Fail before NuGet if the declared SDK root cannot resolve the caller."""
    return """sdk_uid=$(id -u)
sdk_gid=$(id -g)
if ! getent passwd "$sdk_uid" >/dev/null || ! getent group "$sdk_gid" >/dev/null; then
    echo "SDK native root cannot resolve UID $sdk_uid / GID $sdk_gid; declared defaults are root (0) and builder (1000). Run with a declared account; native x64 qualification uses builder 1000." >&2
    exit 1
fi
"""
