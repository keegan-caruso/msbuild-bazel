"""Compare production qualification fingerprints and paired immutable-SDK timings.

Build ProjectSync first. Set RULES_MSBUILD_DOTNET_ROOT to the selected SDK.
Pass --full on the Linux qualification host with /usr/bin/bwrap installed.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
ENV = dict(os.environ, DOTNET_ROOT=str(SDK), DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1',
           DOTNET_GENERATE_ASPNET_CERTIFICATE='false', DOTNET_NOLOGO='1')


def main():
    with tempfile.TemporaryDirectory(prefix='qualification-environment-') as temporary:
        work = Path(temporary)
        ENV['DOTNET_CLI_HOME'] = str(work / 'dotnet-home')
        harness = work / 'harness'
        harness.mkdir()
        (harness / 'Program.cs').write_text((ROOT / 'tests/graph_build/QualificationEnvironment.cs.txt').read_text())
        (harness / 'Harness.csproj').write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net11.0</TargetFramework>'
            '<OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
            '</PropertyGroup></Project>')
        subprocess.run([str(SDK / 'dotnet'), 'build', str(harness / 'Harness.csproj'), '-c', 'Release',
                        '--nologo', '-p:UseSharedCompilation=false'], env=ENV, check=True)
        subprocess.run([str(SDK / 'dotnet'), str(harness / 'bin/Release/net11.0/Harness.dll'),
                        str(ROOT / 'tools/ProjectSync/bin/Release/net11.0/ProjectSync.dll'),
                        str(work / 'fixtures'), '--sdk', str(SDK), *sys.argv[1:]], env=ENV, check=True)


if __name__ == '__main__':
    main()
