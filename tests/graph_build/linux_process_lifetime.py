"""Reproduce Linux creator-thread death and qualify the worker launch lifetime.

Namespace flags and --die-with-parent stay enabled. This checks process lifetime,
not filesystem hermeticity; the probe mounts distribution tools read-only.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
with tempfile.TemporaryDirectory(prefix='graph-process-lifetime-') as name:
    root = Path(name)
    shutil.copyfile(Path(__file__).with_name('WorkerProcessProbe.cs.txt'), root / 'Program.cs')
    shutil.copyfile(ROOT / 'tools/GraphBuild/WorkerProcess.cs', root / 'WorkerProcess.cs')
    (root / 'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>')
    env = dict(os.environ, DOTNET_ROOT=str(sdk), DOTNET_HOST_PATH=str(sdk / 'dotnet'))
    with (root / 'build.log').open('w') as log:
        subprocess.run([str(sdk / 'dotnet'), 'build', str(root / 'Probe.csproj'), '-c', 'Release', '-p:UseSharedCompilation=false', '-p:NuGetAudit=false'], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    command = [str(sdk / 'dotnet'), str(root / 'bin/Release/net10.0/Probe.dll')]
    baseline = subprocess.check_output(command + ['retire', str(root)], env=env, text=True).strip()
    assert baseline == '137', 'Expected creator-thread death to kill bubblewrap: ' + baseline
    for _ in range(3):
        assert subprocess.check_output(command + ['stable', str(root)], env=env, text=True).strip() == '0'
    parent = subprocess.Popen(command + ['hold', str(root)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not (root / 'ready').exists():
            assert parent.poll() is None, 'Parent exited before sandbox was ready'
            assert time.monotonic() < deadline, 'Sandbox startup timed out'
            time.sleep(.05)
        children = set()
        for process in Path('/proc').iterdir():
            if not process.name.isdigit():
                continue
            try:
                fields = (process / 'stat').read_text().split(') ', 1)[1].split()
                if int(fields[1]) == parent.pid:
                    children.add(int(process.name))
            except FileNotFoundError:
                pass
        assert children, 'Missing sandbox child'
        parent.terminate()
        parent.wait(timeout=5)
        deadline = time.monotonic() + 5
        def live(pid):
            status = Path('/proc/' + str(pid) + '/stat')
            return status.exists() and status.read_text().split(') ', 1)[1].split()[0] != 'Z'
        while any(live(pid) for pid in children):
            assert time.monotonic() < deadline, 'Sandbox survived parent termination'
            time.sleep(.05)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
    print(json.dumps(dict(retiredCreatorExitCode=int(baseline), stableLaunches=3, parentDeathCleanup=True)))
    print('PASS: creator-thread retirement reproduced; dedicated launch survives and parent death still kills the sandbox')
