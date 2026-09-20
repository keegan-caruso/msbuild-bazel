"""Compare fresh processes and a sequential reusable MSBuild host on Orchard inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import select
import shutil
import subprocess
import time


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    binary = args.execroot / 'bazel-out/darwin_arm64-fastbuild/bin'
    requests = sorted((json.loads(p.read_text()) for p in binary.glob('project_*.request.json')),
                      key=lambda r: r['entry'])
    selected = requests[::max(1, len(requests)//args.projects)][:args.projects]
    entry = next(r for r in requests if r['entry'].endswith('OrchardCore.Cms.Web.csproj'))
    if entry not in selected:
        selected.append(entry)
    expected = {}
    records = []
    for batch, mode in enumerate(['fresh', 'worker', 'worker', 'fresh']):
        worker = None
        started = time.perf_counter()
        if mode == 'worker':
            worker = subprocess.Popen([str(args.dotnet), str(args.runner), '--worker-probe'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        rows = []
        try:
            for index, original in enumerate(selected):
                request = dict(original, profileMsbuild=True, validatePublication=True)
                for field in ['output', 'apiOutput', 'runtimeOutput', 'diagnostics']:
                    path = args.output / 'actions' / str(index) / field
                    shutil.rmtree(path, ignore_errors=True)
                    request[field] = str(path)
                path = args.output / 'request.json'
                path.write_text(json.dumps(request))
                begin = time.perf_counter()
                if worker:
                    worker.stdin.write(json.dumps(dict(RequestPath=str(path), WorkingDirectory=str(args.execroot)))+'\n')
                    worker.stdin.flush()
                    if not select.select([worker.stdout], [], [], 300)[0]:
                        raise TimeoutError('Worker request timed out')
                    response = json.loads(worker.stdout.readline())
                    code, log = response['exitCode'], response['output']
                else:
                    process = subprocess.run([str(args.dotnet), str(args.runner), '--portable-request', str(path)],
                        cwd=args.execroot, capture_output=True, text=True, timeout=300)
                    code, log = process.returncode, process.stdout+process.stderr
                elapsed = time.perf_counter()-begin
                (args.output / f'{batch}-{index}.log').write_text(log)
                assert code == 0, (batch, index, original['entry'])
                hashes = {field+'/'+str(p.relative_to(request[field])): hashlib.sha256(p.read_bytes()).hexdigest()
                          for field in ['output', 'apiOutput', 'runtimeOutput']
                          for p in Path(request[field]).rglob('*') if p.is_file()}
                if index not in expected:
                    expected[index] = hashes
                assert hashes == expected[index], ('Outputs differ', batch, original['entry'])
                diagnostics = Path(request['diagnostics'])
                row = dict(project=original['entry'], seconds=elapsed, identicalFiles=len(hashes),
                           phases=json.loads((diagnostics/'timings.json').read_text()),
                           msbuild=json.loads((diagnostics/'msbuild-phases.json').read_text()))
                rows.append(row)
                print(mode, index, original['entry'], round(elapsed, 3), flush=True)
        finally:
            if worker:
                worker.stdin.close()
                try:
                    worker.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    worker.kill(); worker.wait()
        records.append(dict(mode=mode, wallSeconds=time.perf_counter()-started,
                            actionSeconds=sum(r['seconds'] for r in rows), samples=rows))
        (args.output/'report.json').write_text(json.dumps(records, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['execroot', 'output', 'dotnet', 'runner']:
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--projects', type=int, default=8)
    run(parser.parse_args())
