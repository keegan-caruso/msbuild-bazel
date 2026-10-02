"""Isolate SDK JS-discovery cache changes caused by generated apphost timestamps."""

import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qualify import DOTNET, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-static-web-cache-') as temporary:
        root = Path(temporary).resolve()
        project = root / 'Web.csproj'
        project.write_text('<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup>'
                          '<TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings>'
                          '</PropertyGroup></Project>')
        (root / 'Program.cs').write_text('var app = WebApplication.CreateBuilder(args).Build(); app.MapGet("/", () => "ok"); app.Run();')
        run(DOTNET, 'restore', project, '--source', root, '-p:NuGetAudit=false')
        def build():
            run(DOTNET, 'build', project, '-c', 'Release', '--no-restore', '-p:UseSharedCompilation=false')
            return {p.name: json.loads(p.read_text()) for p in (root / 'obj/Release/net10.0').glob('rjsm*.dswa.cache.json')}
        baseline = build()
        assembly = root / 'bin/Release/net10.0/Web.dll'
        before = assembly.read_bytes()
        host = root / ('obj/Release/net10.0/apphost.exe' if os.name == 'nt' else 'obj/Release/net10.0/apphost')
        stamp = host.stat()
        os.utime(host, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 2_000_000_000))
        changed = build()
        assert baseline.keys() == changed.keys() and len(changed) == 2, (baseline, changed)
        for name, old in baseline.items():
            new = changed[name]
            assert old['InputHashes'] != new['InputHashes'], (name, old, new)
            assert {k:v for k,v in old.items() if k != 'InputHashes'} == {k:v for k,v in new.items() if k != 'InputHashes'}
            assert old['CachedAssets'] == new['CachedAssets'] == {}
            assert old['CachedCopyCandidates'] == new['CachedCopyCandidates'] == {}
        assert assembly.read_bytes() == before
        print('PASS: apphost timestamp alone changes JS-discovery input hashes; assemblies and empty asset/copy sets are identical')


if __name__ == '__main__':
    main()
