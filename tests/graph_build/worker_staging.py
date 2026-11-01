"""Compare production broker staging; replace compilation with a byte/mode audit."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import uuid

from qualify import DOTNET


def digest(path):
    with path.open('rb') as source:
        value = hashlib.sha256()
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def audit(request, execroot, staging, prepared):
    manifest = json.loads((prepared / 'prepared/manifest.json').read_text())
    count = size = 0

    def verify(source, destination, mode=None, expected=None):
        nonlocal count, size
        assert not destination.is_symlink()
        assert destination.stat().st_mode & 0o777 == (source.stat().st_mode & 0o777 if mode is None else mode), destination
        assert digest(destination) == (digest(source) if expected is None else expected), destination
        count += 1
        size += destination.stat().st_size

    for name, record in manifest['Files'].items():
        payload = prepared / 'prepared' / name
        verify(payload, payload, record['Mode'], record['Digest'])
    for item in json.loads(request.read_text())['sources']:
        source, destination = execroot / item['path'], staging / 'workspace' / item['destination']
        if source.is_dir():
            for path in source.rglob('*'):
                if path.is_file():
                    verify(path, destination / path.relative_to(source))
        else:
            verify(source, destination)
    (staging / 'report.json').write_text(json.dumps(dict(verified=True, files=count, bytes=size)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='new evidence directory outside the execroot')
    parser.add_argument('--execroot', type=Path, required=True, help='retained fresh Linux graph execroot with all request inputs present')
    parser.add_argument('--request', type=Path, required=True, help='graph action request JSON from that execroot')
    parser.add_argument('--runner', type=Path, action='append', required=True, help='GraphBuild.dll candidates, each with its complete runtime payload')
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--cold', action='store_true', help='drop guest page caches before each sample; disposable Linux VM/root only')
    args = parser.parse_args()
    assert sys.platform == 'linux' and args.samples > 0
    results, execroot, request = (path.resolve() for path in [args.directory, args.execroot, args.request])
    assert not results.is_relative_to(execroot) and not execroot.is_relative_to(results)
    data = json.loads(request.read_text())
    assert data.get('prepared'), 'The probe requires a prepared graph request'
    results.mkdir(parents=True, exist_ok=False)
    script = results / 'audit.sh'
    script.write_text('#!/bin/bash\nset -eu\nexec ' + shlex.join([sys.executable, str(Path(__file__).resolve()),
        '--verify', str(request), str(execroot)]) + ' "$3" "$8"\n')
    runners = [path.resolve() for path in args.runner]
    rows = []
    for sample in range(args.samples):
        for offset in range(len(runners)):
            candidate = (sample + offset) % len(runners)
            runner = runners[candidate]
            control = execroot / ('staging-probe-' + uuid.uuid4().hex)
            control.mkdir()
            data.update(output=str(control.relative_to(execroot) / 'output'), profileBuild=True, evaluationCacheMb=0)
            (control / 'request.json').write_text(json.dumps(data))
            (control / 'params').write_text(str(control.relative_to(execroot) / 'request.json') + '\n')
            try:
                if args.cold:
                    os.sync()
                    Path('/proc/sys/vm/drop_caches').write_text('3\n')
                label = str(sample) + '-' + str(candidate)
                with (results / (label + '.log')).open('w') as log:
                    subprocess.run([str(DOTNET), str(runner), 'worker', str(script), '4096',
                        '@' + str(control.relative_to(execroot) / 'params')], cwd=execroot,
                        stdout=log, stderr=subprocess.STDOUT, check=True)
                row = json.loads((control / 'output/report.json').read_text())
                assert row['verified']
                row.update(sample=sample, candidate=candidate, coldPageCache=args.cold,
                    runnerSha256=digest(runner), scope='isolated production staging, fresh process; child audits bytes/modes instead of building; not end-to-end build timing')
                rows.append(row)
                (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
                print(json.dumps(row), flush=True)
            finally:
                shutil.rmtree(control)


if __name__ == '__main__':
    if len(sys.argv) == 6 and sys.argv[1] == '--verify':
        audit(*(Path(value) for value in sys.argv[2:]))
    else:
        main()
