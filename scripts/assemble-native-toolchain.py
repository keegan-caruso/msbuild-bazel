#!/usr/bin/env python3
"""Assemble pinned Ubuntu native tools with declared Bazel package actions.

Run on Ubuntu 26.04 with dpkg-deb, a host C compiler, Python and the pinned
SDK/Bazel wrappers. The compiler is needed only for Bazel Python launchers.
--prepare-only emits the workspace without executing any Linux actions.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests/runtime'))
from native_environment import load_catalog, build_prefix, sdk_account_check


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(output, architecture, sdk, rules=ROOT):
    catalog = load_catalog(architecture, sdk=sdk)
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / 'workspace'
    workspace.mkdir()
    (output / 'catalog.json').write_text(json.dumps(catalog, indent=2) + '\n')
    shutil.copyfile(rules / 'tests/runtime/native_inputs.bzl', workspace / 'native_inputs.bzl')
    module = ['module(name="native_toolchain_assembly")',
              'bazel_dep(name="rules_msbuild",version="0.0.0")',
              'local_path_override(module_name="rules_msbuild",path=' + json.dumps(str(rules)) + ')',
              'bazel_dep(name="rules_pkg",version="1.3.0")',
              'bazel_dep(name="rules_python",version="1.7.0")',
              'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")',
              'dotnet.sdk(name="controller",version="11.0.100",platforms=["linux-arm64","linux-x64"])',
              'use_repo(dotnet,"controller")', 'register_toolchains("@controller//:all")',
              'http_file=use_repo_rule("@bazel_tools//tools/build_defs/repo:http.bzl","http_file")']
    packages = {}
    for package in catalog['packages']:
        name = 'native_' + package['name'].replace('-', '_').replace('+', 'p')
        module.append('http_file(name=%s,url=%s,sha256=%s,downloaded_file_path=%s)' %
                      tuple(json.dumps(value) for value in [name, package['url'], package['sha256'], package['name'] + '.deb']))
        packages['@' + name + '//file'] = package['sha256']
    (workspace / 'MODULE.bazel').write_text('\n'.join(module) + '\n')
    (workspace / 'BUILD.bazel').write_text('load(":native_inputs.bzl","native_toolchain_inputs")\n'
        'native_toolchain_inputs(name="toolchain",packages=' + json.dumps(packages) + ',architecture=' + json.dumps(architecture) + ',sdk=' + str(sdk) + ')\n')
    return workspace


def probe(output, architecture, sdk, system_bwrap=False):
    root = output / 'sealed'
    root.mkdir()
    subprocess.run([os.environ.get('RULES_MSBUILD_TAR', 'tar'), '-xpf', str(output / 'native.tar'), '-C', str(root)], check=True)
    source = output / 'probe'
    source.mkdir()
    script = build_prefix(architecture) + '''
for tool in clang-18 clang++-18 lld-18 llvm-config-18 python3 cmake ninja pkg-config; do command -v "$tool"; done
printf '#include <stdio.h>\\nint main(void){puts("native compile/link/execute");}\\n' > /source/basic.c
clang-18 /source/basic.c -o /source/basic
/source/basic
'''
    if sdk:
        script += sdk_account_check()
        script += '''
for tool in file cpio python lldb-18 msgfmt localedef pigz time curl; do command -v "$tool"; done
file /usr/bin/file | grep 'ELF 64-bit.*x86-64'
python --version
lldb-18 --version
pkg-config --modversion libbrotlidec
for tool in /usr/bin/file /usr/bin/clang-18 /usr/bin/lldb-18; do
 ldd "$tool" > /source/ldd-$(basename "$tool").txt
 ! grep 'not found' /source/ldd-$(basename "$tool").txt
done
printf '#include <brotli/decode.h>\\nint main(void){return BrotliDecoderVersion() == 0;}\\n' > /source/brotli.c
clang-18 /source/brotli.c -lbrotlidec -o /source/brotli
/source/brotli
test -s /etc/ssl/certs/ca-certificates.crt
'''
    script += 'printf "PASS: sealed native tools, compile/link/execute\\n"\n'
    (source / 'probe.sh').write_text(script)
    sandbox = output / 'bwrap'
    if system_bwrap:
        from system_bwrap import select_sandbox
        sandbox = select_sandbox(sandbox, system_bwrap=True)
    command = [str(sandbox), '--die-with-parent', '--unshare-all', '--new-session', '--cap-drop', 'ALL',
               '--ro-bind', str(root), '/', '--bind', str(source), '/source', '--proc', '/proc', '--dev', '/dev',
               '--tmpfs', '/tmp', '--chdir', '/source', '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin',
               '--setenv', 'HOME', '/tmp', '--setenv', 'LANG', 'C.UTF-8', '--', '/bin/bash', 'probe.sh']
    with (output / 'sealed.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    shutil.rmtree(root)
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--architecture', choices=['arm64', 'x64'], default='arm64')
    parser.add_argument('--sdk', action='store_true')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--system-bwrap', action='store_true', help='Verify and use packaged /usr/bin/bwrap for the sealed probe')
    args = parser.parse_args()
    if args.system_bwrap and not args.probe:
        parser.error('--system-bwrap requires --probe')
    if args.probe and args.prepare_only:
        parser.error('--probe requires execution')
    if not args.prepare_only:
        if platform.system() != 'Linux':
            raise ValueError('Native package assembly requires Ubuntu 26.04')
        release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
        if platform.system() != 'Linux' or release.get('ID', '').strip('"') != 'ubuntu' or release.get('VERSION_ID', '').strip('"') != '26.04':
            raise ValueError('Native package assembly requires Ubuntu 26.04')
        if not Path('/usr/bin/dpkg-deb').is_file():
            raise ValueError('Native package assembly requires /usr/bin/dpkg-deb')
        if not shutil.which('gcc') and not shutil.which('clang'):
            raise ValueError('Bazel package assembly requires a host C compiler for Python launchers')
        expected = 'aarch64' if args.architecture == 'arm64' else 'x86_64'
        if args.probe and platform.machine() != expected:
            raise ValueError('The sealed execution probe requires the selected native architecture')
    output = args.output.resolve()
    workspace = prepare(output, args.architecture, args.sdk)
    if args.prepare_only:
        return
    marker = output / 'case-sensitive-check'
    marker.touch(exist_ok=False)
    try:
        if (output / 'CASE-SENSITIVE-CHECK').exists():
            raise ValueError('Native tool assembly requires a case-sensitive output filesystem')
    finally:
        marker.unlink()
    command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--nosystem_rc', '--nohome_rc', '--noworkspace_rc',
               '--batch', '--output_base=' + str(output / 'bazel')]
    with (output / 'assembly.log').open('w') as log:
        subprocess.run(command + ['build', '//:toolchain', '//:tools', '--jobs=2'], cwd=workspace,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    def artifact(target):
        relative = subprocess.check_output(command + ['cquery', target, '--output=files'], cwd=workspace,
                                           text=True).strip()
        if len(relative.splitlines()) != 1:
            raise ValueError('Expected one native assembly output')
        return workspace / relative
    shutil.copyfile(artifact('//:toolchain'), output / 'native.tar')
    shutil.copyfile(artifact('//:tools') / 'usr/bin/bwrap', output / 'bwrap')
    (output / 'bwrap').chmod(0o755)
    receipt = dict(result='assembled', architecture=args.architecture, sdk=args.sdk, nativeArchiveSha256=digest(output / 'native.tar'),
                   nativeArchiveBytes=(output / 'native.tar').stat().st_size, sandboxSha256=digest(output / 'bwrap'),
                   catalogSha256=digest(output / 'catalog.json'), packageCount=len(load_catalog(args.architecture, args.sdk)['packages']))
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if args.probe:
        receipt['sealedProbe'] = probe(output, args.architecture, args.sdk, args.system_bwrap)
        receipt['systemBwrap'] = args.system_bwrap
        receipt['result'] = 'PASS'
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
