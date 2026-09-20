"""Matched-source raw Orchard clean builds, with and without compiler servers."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def run(a):
    a.output.mkdir(parents=True, exist_ok=False)
    source = a.output / 'source'
    shutil.copytree(a.source, source, ignore=shutil.ignore_patterns('.git', '.nuget', 'bin', 'obj'))
    env = dict(os.environ, DOTNET_ROOT=str(a.dotnet.parent), DOTNET_CLI_HOME=str(a.output / 'home'),
               NUGET_PACKAGES=str(a.packages), MSBuildEnableWorkloadResolver='false',
               DOTNET_EnableDiagnostics='0', DOTNET_CLI_TELEMETRY_OPTOUT='1')
    common = [str(a.dotnet), 'msbuild', 'src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj',
              '-p:Configuration=Release', '-m:2', '-nodeReuse:false', '-nologo']
    rows = []
    def invoke(name, arguments):
        start = time.perf_counter()
        with (a.output / (name + '.log')).open('w') as log:
            p = subprocess.run(common + arguments, cwd=source, env=env, stdout=log,
                               stderr=subprocess.STDOUT, timeout=1200)
        row = dict(case=name, seconds=time.perf_counter()-start, exitCode=p.returncode)
        assert p.returncode == 0, name
        rows.append(row)
        (a.output / 'report.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps(row), flush=True)
    invoke('restore', ['-t:Restore', '-p:RestoreSources=' + str(a.feed), '-p:NuGetAudit=false'])
    for name, shared in [('clean-unshared', False), ('clean-shared', True)]:
        for project in source.rglob('*.csproj'):
            for folder in ['bin', 'obj/Release']:
                shutil.rmtree(project.parent / folder, ignore_errors=True)
        invoke(name, ['-t:Build', '-p:UseSharedCompilation=' + str(shared).lower(),
                      '-verbosity:normal', '-bl:' + str(a.output / (name + '.binlog')) + ';ProjectImports=None'])
        rows[-1]['compilerCommandLines'] = (a.output / (name + '.log')).read_text().count(' /noconfig ')
        assert rows[-1]['compilerCommandLines'] == 202, rows[-1]
        (a.output / 'report.json').write_text(json.dumps(rows, indent=2) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['source', 'output', 'dotnet', 'feed', 'packages']:
        p.add_argument('--' + name, type=Path, required=True)
    run(p.parse_args())
