"""Independent processes publish shared payloads atomically and reject collisions."""
import hashlib
from pathlib import Path
import subprocess
import tempfile

from qualify import DOTNET, ENV, ROOT, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-payload-race-') as temporary:
        root = Path(temporary).resolve()
        source = root / 'payload'
        source.write_bytes(b'parallel shared payload\n' * 50000)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        includes = [ROOT / 'tools/GraphBuild' / name for name in ['SnapshotPayloads.cs', 'Contract.cs', 'GraphProfile.cs']]
        includes.append(ROOT / 'tools/ProjectCache/RemoteSnapshotStore.cs')
        (root / 'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings>'
            '<Nullable>enable</Nullable></PropertyGroup><ItemGroup>' +
            ''.join(f'<Compile Include="{path}" />' for path in includes) + '</ItemGroup></Project>')
        (root / 'Program.cs').write_text('using RulesMSBuild.GraphBuild;\n'
            'new SnapshotPayloads(args[0]).Store(args[1], args[2], args[3]);\n')
        run(DOTNET, 'build', root / 'Probe.csproj', '-c', 'Release')
        program = root / 'bin/Release/net10.0/Probe.dll'
        cache = root / 'cache'
        commands = [[str(p) for p in [DOTNET, program, cache, source, digest, cache / f'snapshot-{i}/payload']] for i in range(12)]
        processes = [subprocess.Popen(command, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for command in commands]
        for process in processes:
            stdout, stderr = process.communicate()
            assert process.returncode == 0, (stdout, stderr)
        blobs = list((cache / '.cas').iterdir())
        assert len(blobs) == 1 and blobs[0].read_bytes() == source.read_bytes()
        assert all((cache / f'snapshot-{i}/payload').read_bytes() == source.read_bytes() for i in range(12))
        source.write_bytes(b'conflicting bytes')
        # A false claimed digest must fail before publication.
        failure = run(DOTNET, program, root / 'fresh-cache', source, digest, root / 'bad-snapshot', success=False)
        assert 'Corrupt graph snapshot payload' in failure.stderr
        assert not (root / 'bad-snapshot').exists()
        assert not list((root / 'fresh-cache/.cas').glob('*.pending-*'))
        print('PASS: twelve independent payload writers, one complete blob, digest rejection and staging cleanup')


if __name__ == '__main__':
    main()
