"""Exercise the actual macOS request sandbox and its owned process group."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import time

from qualify import DOTNET, ROOT, SDK


def wait_until(predicate):
    stop = time.monotonic() + 15
    while not predicate():
        if time.monotonic() > stop:
            raise TimeoutError('Native worker control timed out')
        time.sleep(.05)


def exited(pid):
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True


def main():
    assert platform.system() == 'Darwin' and platform.machine() == 'arm64'
    with tempfile.TemporaryDirectory(prefix='mac-worker-') as name:
        root = Path(name).resolve()
        runner = root / 'runner'
        runner.mkdir()
        outside = root / 'outside'
        outside.write_text('private')
        (runner / 'GraphBuild.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<OutputType>Exe</OutputType><TargetFramework>net11.0</TargetFramework></PropertyGroup></Project>')
        (runner / 'Program.cs').write_text("""
using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
var contract = File.ReadAllLines(args[2]);
var output = Path.GetDirectoryName(args[3])!;
foreach (Action operation in new Action[] {
    () => File.ReadAllText(contract[0]), () => File.WriteAllText(contract[0], "changed"),
    () => File.WriteAllText(Path.Combine(AppContext.BaseDirectory, "unexpected"), "changed")
}) {
    try { operation(); return 3; } catch (UnauthorizedAccessException) {}
}
File.WriteAllText(Path.Combine(Path.GetTempPath(), "scratch"), "allowed");
var helper = Process.Start(new ProcessStartInfo("/bin/sh") {
    ArgumentList = { "-c", "sleep 2; echo late > \\"$1\\"; sleep 60", "sh", Path.Combine(output, "late") }
})!;
File.WriteAllText(Path.Combine(output, "helper"), helper.Id.ToString());
if (contract[1] == "hold") Thread.Sleep(60000);
return 0;
""")
        subprocess.run([DOTNET, 'build', 'GraphBuild.csproj', '-c', 'Release', '--disable-build-servers'],
                       cwd=runner, check=True, timeout=120)
        payload = runner / 'bin/Release/net11.0'
        with subprocess.Popen(['/bin/sleep', '60']) as sibling:
            try:
                for mode in ('normal', 'hold'):
                    output = root / mode
                    (output / 'workspace').mkdir(parents=True)
                    scratch = root / (mode + '-scratch')
                    scratch.mkdir()
                    contract = root / (mode + '-contract')
                    contract.write_text(f'{outside}\n{mode}\n')
                    with subprocess.Popen(['/bin/bash', ROOT / 'msbuild/macos-worker.sh', SDK, payload, output,
                                           contract, scratch, 'Build', 'action', '-', '-', '0', '0'],
                                          stdin=subprocess.PIPE) as group:
                        wait_until(lambda: (output / 'helper').is_file() or group.poll() is not None)
                        helper = int((output / 'helper').read_text())
                        if mode == 'hold':
                            group.stdin.close()  # Broker death closes its private pipe.
                        result = group.wait(timeout=10)
                        assert (result == 0) == (mode == 'normal'), result
                        wait_until(lambda: exited(helper))
                    assert not (output / 'late').exists()
                    assert (scratch / 'tmp/scratch').read_text() == 'allowed'
                    assert sibling.poll() is None and outside.read_text() == 'private'
            finally:
                sibling.terminate()
    print('PASS: declared reads/writes, private input denial, descendant cleanup on success and broker EOF')


if __name__ == '__main__':
    main()
