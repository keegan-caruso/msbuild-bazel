"""Assemble the pinned native packages and execute LLVM inside their declared root."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from source_runtime.acquisition import acquire_source
from source_runtime.common import digest, read_recipe
from source_runtime.native import declare_inputs, prepare_inputs
from native_environment import build_prefix


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='new disposable Linux ARM64 qualification directory')
    parser.add_argument('--source-archive', type=Path)
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'aarch64':
        parser.error('Requires native Linux ARM64')
    base = args.output.resolve()
    base.mkdir(parents=True, exist_ok=False)
    (base / 'reports').mkdir()
    env = dict(os.environ)
    source = acquire_source(base, read_recipe()['source'], env, args.source_archive)
    prepare_inputs(base / 'preparation', source)
    workspace = base / 'workspace'
    shutil.copytree(ROOT / 'examples/quickstart', workspace)
    module = workspace / 'MODULE.bazel'
    module.write_text(module.read_text().replace('path = "../msbuild-bazel"', 'path = ' + json.dumps(str(ROOT))) +
        '\nbazel_dep(name="rules_pkg",version="1.3.0")\nbazel_dep(name="rules_python",version="1.7.0")\n')
    provenance = declare_inputs(workspace, base / 'preparation')
    native = workspace / 'native'
    (native / 'probe.sh').write_text(build_prefix() + '''{
cat /etc/os-release
clang-18 --version
clang-18 -dumpmachine
sha256sum /usr/lib/llvm-18/bin/clang
for tool in bash cp mv uname sha256sum clang-18 clang ld.lld llvm-ar python3 cmake ninja pkg-config; do command -v "$tool"; done
} > proof.txt
printf 'int main(void) { return 0; }\\n' > proof.c
clang-18 -Werror proof.c -o proof
./proof
mkdir result
cp proof.txt result/
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -cf result.tar -C result .
''')
    with (native / 'BUILD.bazel').open('a') as build:
        build.write('\nnative_runtime(name="environment_probe",driver=":driver",sandbox=":bwrap",toolchain_archive=":toolchain",source_archive=":sources",script="probe.sh",products={"proof":"proof.txt"})\n')
    launcher = env.get('RULES_MSBUILD_BAZEL', str(ROOT / 'scripts/bazel-launcher.sh'))
    command = [launcher, '--nosystem_rc', '--nohome_rc', '--noworkspace_rc',
               '--output_base=' + str(base / 'bazel')]
    metrics = dict(rssSumPeakKiB=0, minMemAvailableKiB=None, samples=0)
    stopped = threading.Event()

    def monitor():
        while not stopped.is_set():
            memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
            available = int(memory['MemAvailable'].split()[0])
            metrics['memTotalKiB'] = int(memory['MemTotal'].split()[0])
            metrics['minMemAvailableKiB'] = min(metrics['minMemAvailableKiB'] or available, available)
            rss = 0
            for status in Path('/proc').glob('[0-9]*/status'):
                try:
                    rss += sum(int(line.split()[1]) for line in status.read_text().splitlines() if line.startswith('VmRSS:'))
                except (FileNotFoundError, ProcessLookupError):
                    pass
            metrics['rssSumPeakKiB'] = max(metrics['rssSumPeakKiB'], rss)
            metrics['samples'] += 1
            stopped.wait(0.25)

    observer = threading.Thread(target=monitor, daemon=True)
    observer.start()
    began = time.monotonic()
    try:
        with (base / 'reports/assembly.log').open('w') as log:
            subprocess.run(command + ['build', '//native:environment_probe', '--jobs=2',
                '--local_test_jobs=1', '--worker_max_instances=MSBuildGraph=1'], cwd=workspace,
                env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)
        proof = workspace / 'bazel-bin/native/environment_probe.generated/proof.txt'
        shutil.copyfile(proof, base / 'reports/proof.txt')
        metrics.update(seconds=time.monotonic() - began, nativePackagesSha256=digest(ROOT / 'tests/runtime/native-packages.json'),
            toolchainSha256=digest(workspace / 'bazel-bin/native/toolchain.tar'), provenance=provenance,
            memoryMethod='0.25s guest-wide summed process VmRSS (shared pages can be counted more than once) and MemAvailable')
        print((base / 'reports/proof.txt').read_text(), end='')
        print('PASS: declared Ubuntu 26.04 ARM64 LLVM 18.1.8 package assembly, C compilation/link and execution')
    finally:
        stopped.set()
        observer.join()
        (base / 'reports/resources.json').write_text(json.dumps(metrics, indent=2) + '\n')
        subprocess.run(command + ['shutdown'], cwd=workspace, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


if __name__ == '__main__':
    main()
