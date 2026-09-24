"""Restore/build a real ASP.NET Core managed workload, retaining upstream imports.

Run inside the qualified Linux container. Acquisition/restore are measured separately
from compilation. No project source, target, or analyzer is disabled by this harness.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser()
parser.add_argument('checkout', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--jobs', type=int, default=2)
parser.add_argument('--phase', choices=['select', 'restore', 'build', 'clean'], default='select')
args = parser.parse_args()
root = args.checkout.resolve()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=True)
areas = ['Http', 'Middleware', 'Mvc', 'SignalR', 'Servers', 'Security',
         'Hosting', 'Caching', 'DataProtection', 'Identity']
if args.phase == 'select':
    revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != '7387de91234d3ef751fa50b3d1bfede4130213ff':
        raise SystemExit('Unexpected ASP.NET Core revision: ' + revision)
    entries = sorted(p.relative_to(root).as_posix() for area in areas
                     for p in (root / 'src' / area).rglob('*.csproj')
                     if p.parent.name in ('src', 'test') and not
                     {'samples', 'testassets', 'perf', 'benchmarkapps', 'obj', 'bin'}.intersection(p.parts))
    (out / 'selection.json').write_text(json.dumps({'areas': areas, 'entries': entries}, indent=2) + '\n')
    project = ET.Element('Project')
    group = ET.SubElement(project, 'ItemGroup')
    for entry in entries:
        ET.SubElement(group, 'SelectedProject', Include=str(root / entry))
    for target in ['Restore', 'Build', 'Clean']:
        node = ET.SubElement(project, 'Target', Name=target)
        ET.SubElement(node, 'MSBuild', Projects='@(SelectedProject)', Targets=target,
                      BuildInParallel='true', Properties='Configuration=Release')
    ET.indent(project)
    ET.ElementTree(project).write(out / 'Workload.proj', encoding='unicode')
    print(f'Selected {len(entries)} entry projects; dependency closure not counted yet.')
else:
    command = [str(root / '.dotnet/dotnet'), 'msbuild', str(out / 'Workload.proj'),
               '-t:' + args.phase.title(), '-m:' + str(args.jobs), '-v:minimal',
               '-p:WarningsNotAsErrors=CS8629%3BIDE0031',
               '-bl:' + str(out / (args.phase + '.binlog'))]
    start = time.perf_counter()
    with (out / (args.phase + '.log')).open('w') as log:
        result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
    report = {'command': command, 'exitCode': result.returncode,
              'seconds': time.perf_counter() - start}
    (out / (args.phase + '.json')).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)
    result.check_returncode()
