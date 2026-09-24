"""Linux scratch leases protect active workers and reclaim state after SIGKILL."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

rules = Path(__file__).resolve().parents[2]
command = [str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'), str(rules/'tools/ExplicitBuild/bin/Release/net10.0/ExplicitBuild.dll'), '--bazel-worker', '--persistent_worker']
with tempfile.TemporaryDirectory() as temporary:
    folder = Path(temporary)
    parent = folder/('rules-msbuild-workers-'+str(os.geteuid()))
    children = []
    def roots():
        return {p.stem for p in parent.glob('*.lease')}
    def start():
        before = roots()
        process = subprocess.Popen(command, cwd=folder, env=dict(os.environ, TMPDIR=str(folder)), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        children.append(process)
        deadline = time.monotonic()+30
        while not (roots()-before):
            assert process.poll() is None, process.communicate()
            assert time.monotonic() < deadline, 'Worker did not create its lease'
            time.sleep(.02)
        created = roots()-before
        assert len(created) == 1, created
        root = parent/created.pop()
        while not root.is_dir():
            assert time.monotonic() < deadline
            time.sleep(.02)
        return process, root
    try:
        first, dead = start()
        (dead/'retained-cache-control').write_text('reclaim this abandoned state')
        second, live = start()
        assert dead.is_dir(), 'Starting another worker deleted live state'
        assert (parent/(dead.name+'.lease')).is_file()
        first.kill(); first.communicate(timeout=30)
        third, fresh = start()
        assert not dead.exists() and not (parent/(dead.name+'.lease')).exists()
        assert live.is_dir() and fresh.is_dir(), 'Reclamation deleted an active worker'
        for child in [second, third]:
            stdout, stderr = child.communicate('', timeout=30)
            assert child.returncode == 0, (stdout, stderr)
        assert not roots() and not list(parent.iterdir()), list(parent.iterdir())
        assert (parent.stat().st_mode & 0o777) == 0o700
        def rejected():
            result = subprocess.run(command, cwd=folder, env=dict(os.environ, TMPDIR=str(folder)), input='', capture_output=True, text=True, timeout=30)
            assert result.returncode == 1 and 'private, owned, non-symlink' in result.stderr, (result.stdout, result.stderr)
        parent.chmod(0o755); rejected(); parent.chmod(0o700)
        if os.geteuid() == 0:
            os.chown(parent, 65534, -1)
            try:
                rejected()
            finally:
                os.chown(parent, 0, -1)
        parent.rmdir()
        outside = folder/'outside'; outside.mkdir(); sentinel = outside/'keep'; sentinel.write_text('untouched')
        parent.symlink_to(outside, target_is_directory=True)
        try:
            rejected()
            assert sentinel.read_text() == 'untouched' and list(outside.iterdir()) == [sentinel]
        finally:
            parent.unlink()
        print(json.dumps(dict(abandonedStateRemoved=True, activeWorkersPreserved=True, gracefulCleanup=True, unsafeParentsRejected=True)))
    finally:
        for child in children:
            if child.poll() is None:
                child.kill(); child.communicate(timeout=30)
