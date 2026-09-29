"""Signing keys outside the project directory are declared and invalidate replay."""

import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-signing-') as temporary:
        base = Path(temporary).resolve()
        generator = base / 'keygen'
        generator.mkdir()
        (generator / 'keygen.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup></Project>')
        (generator / 'Program.cs').write_text('using System; using System.IO; using System.Security.Cryptography; using var rsa=new RSACryptoServiceProvider(2048); var key=rsa.ExportCspBlob(true); BitConverter.GetBytes(0x2400).CopyTo(key,4); File.WriteAllBytes(args[0],key);')
        run(DOTNET, 'build', generator / 'keygen.csproj', '-c', 'Release', '-p:NuGetAudit=false')
        root = base / 'workspace'
        (root / 'Library').mkdir(parents=True)
        (root / 'keys').mkdir()
        key = root / 'keys/test.snk'
        def new_key():
            run(DOTNET, generator / 'bin/Release/net10.0/keygen.dll', key)
        new_key()
        (root / 'Library/Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><SignAssembly>true</SignAssembly><AssemblyOriginatorKeyFile>../keys/test.snk</AssemblyOriginatorKeyFile></PropertyGroup></Project>')
        (root / 'Library/Code.cs').write_text('public class Library {}')
        sync = [DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root, SDK / 'sdk/10.0.400', 'Library/Library.csproj', '--graph']
        run(*sync)
        contract = root / 'graph.generated.json'
        assert 'keys/test.snk' in contract.read_text()
        report = base / 'report.json'
        def build(hits):
            for name in ['bin', 'obj']:
                shutil.rmtree(root / 'Library' / name, ignore_errors=True)
            run(DOTNET, RUNNER, 'action', root, contract, report, base / 'cache')
            assert json.loads(report.read_text())['hits'] == hits
            return (root / 'Library/bin/Release/net10.0/Library.dll').read_bytes()
        before = build(0)
        assert build(1) == before
        new_key()
        run(*sync, '--check')
        after = build(0)
        assert after != before
        assert build(1) == after
        key.unlink()
        assert 'Missing signing key input' in run(*sync, success=False).stderr
        print('PASS: signed build/replay, key change invalidation and missing-key rejection')


if __name__ == '__main__':
    main()
