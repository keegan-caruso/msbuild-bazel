"""Check Windows isolation architecture selection and actual marshalled layouts."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
    dotnet = sdk / ('dotnet.exe' if os.name == 'nt' else 'dotnet')
    runner = ROOT / 'tools/GraphBuild/bin/Release/net11.0/GraphBuild.dll'
    with tempfile.TemporaryDirectory(prefix='wabi-') as temporary:
        base = Path(temporary)
        (base / 'Program.cs').write_text((ROOT / 'tests/graph_build/WindowsAbi.cs.txt').read_text())
        (base / 'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net11.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable><UseSharedCompilation>false</UseSharedCompilation></PropertyGroup></Project>')
        (base / 'NuGet.Config').write_text('<configuration><packageSources><clear /></packageSources></configuration>')
        def run(*args):
            result = subprocess.run([str(dotnet), *map(str, args)], text=True, capture_output=True, timeout=120)
            assert result.returncode == 0, result.stdout + result.stderr
            return result.stdout
        run('build', base / 'Probe.csproj', '-c', 'Release', '-warnaserror', '--disable-build-servers', '-p:NuGetAudit=false')
        result = json.loads(run(base / 'bin/Release/net11.0/Probe.dll', runner))
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
