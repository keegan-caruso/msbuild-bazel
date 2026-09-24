"""Repeat a bazel-bench configuration with the shared timer and matched startup."""
import argparse
import csv
import json
from pathlib import Path
import shlex
import statistics
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.measure import command
from benchmarks.run import summarize


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('benchmark', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    config = json.loads((a.benchmark/'config.json').read_text())
    summarize(a.benchmark/'raw.csv', config['global_options']['runs'], len(config['units']))
    metadata = json.loads((a.benchmark/'metadata.json').read_text())
    a.output.mkdir(parents=True, exist_ok=False)
    with (a.benchmark/'raw.csv').open() as stream:
        upstream = list(csv.DictReader(stream))
    results = []
    # Use a fresh clone, just as upstream does; no edits to the prepared source.
    workspace = a.output/'workspace'
    subprocess.run(['git', 'clone', '--quiet', config['global_options']['project_source'], str(workspace)], check=True)
    subprocess.run(['git', '-C', str(workspace), 'checkout', '--quiet', config['global_options']['project_commit']], check=True)
    for index, unit in enumerate(config['units']):
        args = shlex.split(unit['command'])
        build_index = args.index('build')
        startup = [unit['bazel_binary'], '--output_base='+str(a.output/f'base-{index}'), *args[1:build_index]]
        build = [*startup, *args[build_index:], '--nostamp', '--noshow_progress', '--color=no']
        clean = metadata['mode'] != 'noop'
        def reset():
            if clean:
                subprocess.run([*startup, 'clean'], cwd=workspace, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run([*startup, 'shutdown'], cwd=workspace, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        samples = []
        try:
            warm, _ = command(build, workspace, a.output/f'{index}-warmup.log')
            if warm.returncode:
                raise RuntimeError('Warm-up failed')
            reset()
            for iteration in range(config['global_options']['runs']):
                # bazel-bench starts/locates the server before its wall timer.
                subprocess.run([*startup, 'info', 'server_pid'], cwd=workspace, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                profile = a.output/f'{index}-{iteration}.profile.gz'
                result, seconds = command([*build, '--experimental_generate_json_trace_profile', '--profile='+str(profile)], workspace, a.output/f'{index}-{iteration}.log')
                if result.returncode:
                    raise RuntimeError('Comparison sample failed')
                samples.append(seconds)
                # Match upstream's five untimed heap probes; they trigger GC.
                for _ in range(5):
                    subprocess.run([*startup, 'info', 'used-heap-size-after-gc'], cwd=workspace, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                reset()
        finally:
            subprocess.run([*startup, 'shutdown'], cwd=workspace, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        baseline = [float(row['wall']) for row in upstream if row['bazel_commit'] == unit['bazel_binary']]
        results.append(dict(bazel=unit['bazel_binary'], timingScope='server-startup-excluded',
            sharedTimerSamples=samples, bazelBenchSamples=baseline,
            sharedTimerMedian=statistics.median(samples), bazelBenchMedian=statistics.median(baseline)))
        (a.output/'comparison.json').write_text(json.dumps(results, indent=2)+'\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
