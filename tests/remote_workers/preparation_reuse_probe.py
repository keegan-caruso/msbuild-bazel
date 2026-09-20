"""Same-input, same-path discovery comparison with complete output parity."""
import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    original = json.loads(args.request.read_text())
    request = dict(original, output=str(output / 'action/discovery'),
                   diagnostics=str(output / 'diagnostics'))
    request['projectOutputs'] = {name: str(output / 'action/templates' / str(i))
                                for i, name in enumerate(original['projectOutputs'])}
    path = output / 'request.json'
    path.write_text(json.dumps(request))
    expected = None
    records = []
    for i, mode in enumerate(['baseline', 'candidate', 'candidate', 'baseline']):
        shutil.rmtree(output / 'action', ignore_errors=True)
        shutil.rmtree(output / 'diagnostics', ignore_errors=True)
        runner = args.baseline if mode == 'baseline' else args.candidate
        start = time.perf_counter()
        with (output / ('run-' + str(i) + '.log')).open('w') as log:
            process = subprocess.run([str(args.dotnet), str(runner), 'owned-prepare',
                                      '--request', str(path)], cwd=args.execroot,
                                     stdout=log, stderr=subprocess.STDOUT, timeout=600)
        seconds = time.perf_counter() - start
        assert process.returncode == 0, (mode, i)
        hashes = {str(p.relative_to(output / 'action')): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (output / 'action').rglob('*') if p.is_file()}
        if expected is None:
            expected = hashes
        else:
            assert hashes == expected, [k for k in hashes if hashes[k] != expected.get(k)][:10]
        report = json.loads((output / 'diagnostics/report.json').read_text())
        assert report['accepted']
        record = dict(mode=mode, seconds=seconds, identicalFiles=len(hashes), report=report)
        records.append(record)
        (output / 'report.json').write_text(json.dumps(records, indent=2) + '\n')
        print(mode, round(seconds, 3), len(hashes), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['output', 'request', 'execroot', 'dotnet', 'baseline', 'candidate']:
        parser.add_argument('--' + name, type=Path, required=True)
    run(parser.parse_args())
