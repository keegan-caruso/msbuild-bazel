"""Compare batch/server no-op builds while retaining profiles and action evidence."""
import argparse
import gzip
import json
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import subprocess
import tempfile
import time

from bazel_session import BazelSession
from probe_bazel import BAZEL, DOTNET, json_stream, probe


def benchmark(output, samples=3):
    output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='bazel-performance-'))
    try:
        probe(root / 'fixture')
        workspace = root / 'fixture/workspace'
        env = dict(os.environ, DOTNET_ROOT=str(DOTNET.parent), DOTNET_NOLOGO='1',
                   DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_CLI_HOME=str(root / 'home'))
        report = {'schemaVersion': 1, 'platform': platform.platform(),
                  'samplesPerMode': samples, 'modes': {}}
        strategy = 'darwin-sandbox' if platform.system() == 'Darwin' else 'linux-sandbox'
        for mode in ('batch', 'server'):
            directory = root / mode
            directory.mkdir()
            evidence = output / mode
            evidence.mkdir()
            records = []
            with BazelSession(evidence, mode=mode) as session:
                for name in ['warmup', *[f'noop-{i + 1}' for i in range(samples)]]:
                    profile = evidence / f'{name}.profile.json.gz'
                    execution = evidence / f'{name}.execution.json'
                    command = [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc',
                               f'--output_base={directory / "base"}',
                               f'--output_user_root={directory / "user"}',
                               'build', '//:app', f'--disk_cache={directory / "cache"}',
                               f'--spawn_strategy={strategy}', f'--strategy=MsbuildProject={strategy}',
                               '--jobs=2', '--noshow_progress', '--color=no', '--curses=no',
                               f'--profile={profile}', f'--execution_log_json_file={execution}']
                    command = session.prepare(command, workspace, env)
                    started = time.monotonic()
                    result = subprocess.run(command, cwd=workspace, env=env, text=True,
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
                    elapsed = time.monotonic() - started
                    (evidence / f'{name}.log').write_text(result.stdout)
                    if result.returncode:
                        raise RuntimeError(f'{mode}/{name} failed; see its log')
                    actions = [r for r in json_stream(execution) if r.get('mnemonic') == 'MsbuildProject']
                    if name != 'warmup' and actions:
                        raise RuntimeError(f'{mode}/{name} was not a no-op')
                    if name == 'warmup' and (len(actions) != 2 or any(r.get('cacheHit') for r in actions)):
                        raise RuntimeError(f'{mode} warmup did not execute both projects')
                    with gzip.open(profile, 'rt') as stream:
                        trace = json.load(stream)
                    longest = sorted((e for e in trace['traceEvents'] if e.get('ph') == 'X' and 'dur' in e),
                                     key=lambda e: e['dur'], reverse=True)[:15]
                    timing = re.search(r'Elapsed time: ([\d.]+)s, Critical Path: ([\d.]+)s', result.stdout)
                    records.append({'name': name, 'wallSeconds': round(elapsed, 4),
                                    'bazelSeconds': float(timing[1]) if timing else None,
                                    'criticalPathSeconds': float(timing[2]) if timing else None,
                                    'msbuildActionCount': len(actions),
                                    'longestTraceEvents': [{'name': e['name'], 'seconds': e['dur'] / 1e6} for e in longest]})
                    print(f'{mode}/{name}: {elapsed:.3f}s, {len(actions)} MSBuild actions', flush=True)
            report['modes'][mode] = {'runs': records,
                                     'medianNoopSeconds': statistics.median(r['wallSeconds'] for r in records[1:])}
            (output / 'performance.json').write_text(json.dumps(report, indent=2) + '\n')
        return report
    except BaseException:
        diagnostic = output / 'fixture-diagnostics'
        diagnostic.mkdir(exist_ok=True)
        for source in (root / 'fixture').glob('*'):
            if source.is_file() and (source.suffix == '.log' or source.name == 'report.json'):
                shutil.copyfile(source, diagnostic / source.name)
        raise
    finally:
        for directory, _, _ in os.walk(root, followlinks=False):
            path = Path(directory)
            path.chmod(path.stat().st_mode | 0o700)
        shutil.rmtree(root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--samples', default=3, type=int)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error('--samples must be positive')
    benchmark(args.output, args.samples)
