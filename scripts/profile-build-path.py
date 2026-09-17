"""Attribute preparation time without changing production validation or publication.

Run inside the pinned Nix shell. Diagnostic profiles are separate from five
uninstrumented samples; profile timings are never used as speedup measurements.
"""
import argparse
import cProfile
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import pstats
import shutil
import statistics
import subprocess
import sys
import tarfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import prepare_graph as preparation
from probe_graph_cache import cache_environment
from probe_serilog_tests import PROJECT, REVISION, APPROVED, FACT
from synthetic_graph import generate


def inventory(root):
    # Build logs contain durations but are not declared compilation inputs.
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and not p.name.endswith('-build.log')}


def measure(workspace, manifest, output, environment, tests, diagnostic):
    events, reads = [], Counter()
    original_run = subprocess.run
    original_read = Path.read_bytes

    def run(command, *args, **kwargs):
        started = time.perf_counter()
        try:
            return original_run(command, *args, **kwargs)
        finally:
            events.append(dict(command=list(map(str, command)), seconds=time.perf_counter()-started))

    def read(path):
        value = original_read(path)
        reads[str(path)] += 1
        return value

    profile = cProfile.Profile()
    started = time.perf_counter()
    if diagnostic:
        with patch.object(subprocess, 'run', run), patch.object(Path, 'read_bytes', read):
            profile.enable()
            graph = preparation.prepare(workspace, manifest, output, environment=environment, tests=tests)
            profile.disable()
        profile.dump_stats(str(output.parent / 'prepare.prof'))
        stats = pstats.Stats(profile)
        functions = [dict(file=key[0], line=key[1], function=key[2], primitiveCalls=value[0],
                          calls=value[1], selfSeconds=value[2], cumulativeSeconds=value[3])
                     for key, value in stats.stats.items()]
        functions.sort(key=lambda item: item['cumulativeSeconds'], reverse=True)
        details = dict(subprocesses=events, topCumulative=functions[:60],
                       topSelf=sorted(functions, key=lambda item: item['selfSeconds'], reverse=True)[:40],
                       readBytesCalls=sum(reads.values()), uniqueReadBytesPaths=len(reads),
                       mostRepeatedReads=reads.most_common(20))
    else:
        graph = preparation.prepare(workspace, manifest, output, environment=environment, tests=tests)
        details = None
    elapsed = time.perf_counter()-started
    inputs = graph.get('graphInputs', []) + [i for n in graph['nodes'] for i in n['inputs']]
    return dict(seconds=elapsed, diagnostic=details, nodes=len(graph['nodes']),
                inputRecords=len(inputs), uniqueInputPaths=len({i['path'] for i in inputs}),
                buildFileBytes=(output/'BUILD.bazel').stat().st_size,
                outputFiles=sum(p.is_file() for p in output.rglob('*')))


def main(args):
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    workspace = root / 'source'
    report = dict(accepted=False, scope='preparation profiling, not end-to-end performance qualification',
        revision=subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
        workload=args.workload, nodes=args.nodes, shape=args.shape, repetitions=5,
        caveat='Serial shared host; diagnostic cProfile overhead excluded from baseline timings. Setup and restore excluded.', samples=[])
    try:
        if args.workload == 'serilog':
            archive = subprocess.check_output(['git','-C',str(args.source),'archive',REVISION])
            with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
                bundle.extractall(workspace, filter='data')
            shutil.copytree(args.packages, workspace/'.nuget/packages')
            entry = PROJECT
        else:
            spec = generate(workspace, args.nodes, args.shape)
            entry = spec['entry']
        environment = cache_environment(root, workspace)
        dotnet = preparation.DOTNET_ROOT / 'dotnet'
        restore = subprocess.run([str(dotnet),'restore',str(workspace/entry),'-p:Configuration=Release',
            '-p:TargetFramework=net10.0','--packages',str(workspace/'.nuget/packages')], env=environment,
            text=True, capture_output=True)
        (root/'restore.log').write_text(restore.stdout+restore.stderr)
        restore.check_returncode()
        (workspace/'.nuget/packages').mkdir(parents=True, exist_ok=True)
        manifest, request = root/'manifest.json', root/'request.json'
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(workspace),
            dotnetRoot=str(preparation.DOTNET_ROOT), sdkVersion='10.0.400',
            packageRoot=str(workspace/'.nuget/packages'),
            entryPoints=[dict(project=entry,globalProperties=dict(Configuration='Release',TargetFramework='net10.0'))],output=str(manifest))))
        started = time.perf_counter()
        export = subprocess.run([str(dotnet),str(preparation.ROOT/'tools/GraphExport/bin/Release/net10.0/GraphExport.dll'),
            '--request',str(request)],env=environment,text=True,capture_output=True)
        report['initialExportSeconds']=time.perf_counter()-started
        (root/'export.log').write_text(export.stdout+export.stderr)
        export.check_returncode()
        graph=json.loads(manifest.read_text())
        tests=None
        if args.workload=='serilog':
            node=next(n['id'] for n in graph['nodes'] if n['project']=='workspace/'+PROJECT)
            tests=[dict(node=node,data=['test/Serilog.ApprovalTests/ApiApprovalTests.cs',APPROVED],expectedTests=[FACT])]
        report['warmup']=measure(workspace,manifest,root/'warmup',environment,tests,False)
        expected=inventory(root/'warmup')
        for i in range(5):
            output=root/str(i)
            report['samples'].append(measure(workspace,manifest,output,environment,tests,False))
            assert inventory(output)==expected,'prepared payload differs'
        report['profile']=measure(workspace,manifest,root/'profile',environment,tests,True)
        assert inventory(root/'profile')==expected,'profiled payload differs'
        report.update(accepted=True,medianSeconds=statistics.median(s['seconds'] for s in report['samples']),
            payloadEqual=True,excludedFromPayloadComparison='*-build.log diagnostics only')
    except BaseException as error:
        report['failure']=dict(type=type(error).__name__,message=str(error))
        raise
    finally:
        (root/'report.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workload',choices=('serilog','synthetic'),required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source',type=Path)
    parser.add_argument('--packages',type=Path)
    parser.add_argument('--nodes',type=int,default=10)
    parser.add_argument('--shape',choices=('chain','fan'),default='fan')
    main(parser.parse_args())
