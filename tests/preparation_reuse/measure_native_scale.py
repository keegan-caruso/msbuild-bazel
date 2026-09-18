"""Complete native Build versus raw MSBuild on owned 10/100-project fan graphs.

Restore/acquisition and post-run byte/runtime oracles are excluded from both
wall-time measurements. All preparation, staging, Bazel and publication are in.
This is Build-only evidence, not a larger upstream test suite or remote worker.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from native_workflow import Workflow, BAZEL, DOTNET_ROOT, remove_tree
from portable_cache import environment
from probe_native_serilog import hashes
from protected_store import ProtectedStore
from synthetic_graph import generate, name, source, oracle


def measure(output, counts, repetitions):
    output.mkdir(parents=True, exist_ok=False)
    report = dict(accepted=False, scope=__doc__, repetitions=repetitions, counts=counts, samples=[],
                  profile='retained controller, protected Nix store, guarded source refresh',
                  order='alternate raw/native by repetition', budget='unchanged/leaf median <= raw median * 1.25 + 0.250s')
    (output / 'protocol.json').write_text(json.dumps({k:v for k,v in report.items() if k not in ('samples', 'accepted')}, indent=2))
    states = []
    def shutdown(state):
        if (state / 'g').exists():
            subprocess.run([str(BAZEL), '--nohome_rc', '--noworkspace_rc', '--output_base=' + str(state / 'b'),
                '--output_user_root=' + str(state / 'u'), 'shutdown'], cwd=state / 'g', check=True, capture_output=True)
    def command(args, cwd, log):
        result = subprocess.run(list(map(str, args)), cwd=cwd,
            env=dict(environment(DOTNET_ROOT, output / 'home', output, cwd), MSBuildEnableWorkloadResolver='false'),
            capture_output=True, text=True, timeout=900)
        text = result.stdout + result.stderr; log.write_text(text)
        if result.returncode: raise RuntimeError('command failed: ' + str(log))
        return text
    try:
        for count in counts:
            for rep in range(repetitions):
                base = output / f'{count}-{rep}'; base.mkdir()
                src, raw_src = base / 's', base / 'r'
                spec = generate(src, count, 'fan'); generate(raw_src, count, 'fan')
                for root in (src, raw_src):
                    # Retain explicit configured net10 nodes during SDK reference
                    # negotiation, matching the current native qualification.
                    props = root / 'Directory.Build.props'
                    props.write_text(props.read_text().replace('TargetFramework>', 'TargetFrameworks>'))
                    command([DOTNET_ROOT / 'dotnet', 'msbuild', spec['entry'], '-t:Restore', '-p:Configuration=Release',
                        '-p:TargetFramework=net10.0', '-nodeReuse:false', '-nologo'], root, base / (root.name + '-restore.log'))
                state = base / 'state'; states.append(state)
                workflow = Workflow(src, state, spec['entry'], reuse=True, protected_store=ProtectedStore(), incremental_sources=True)
                for case in ('cold', 'seeded', 'unchanged', 'leaf', 'recovery'):
                    expected = oracle(spec['edges'], count - 2 if case in ('leaf', 'recovery') else None)
                    if case == 'leaf':
                        for root in (src, raw_src):
                            (root / name(count - 2) / 'Value.cs').write_text(source(count - 2, spec['edges'][count - 2], False, True))
                    if case == 'recovery':
                        # Keep only the native project bundles; erase Bazel and
                        # preparation state and every raw build output.
                        shutdown(state)
                        for key in ('g', 'b', 'u', 'preparation'): remove_tree(state / key)
                        for path in raw_src.glob('*/bin'): remove_tree(path)
                        for path in raw_src.glob('*/obj/Release'): remove_tree(path)
                        workflow = Workflow(src, state, spec['entry'], reuse=True, protected_store=ProtectedStore(), incremental_sources=True)
                    def raw():
                        start = time.perf_counter()
                        log = command([DOTNET_ROOT / 'dotnet', 'msbuild', spec['entry'], '-t:Build', '-p:Configuration=Release',
                            '-p:TargetFramework=net10.0', '-p:PathMap=' + str(raw_src) + '=/_/workspace', '-graphBuild', '-isolateProjects',
                            '-m:2', '-nodeReuse:false', '-nologo', '-v:normal'], raw_src, base / (case + '-raw.log'))
                        elapsed = time.perf_counter() - start
                        compiles = sum('/Roslyn/bincore/csc' in line and ' /noconfig ' in line for line in log.splitlines())
                        return dict(seconds=elapsed, compiles=compiles)
                    def native(): return workflow.run(base / (case + '-native'))
                    if rep % 2: n, r = native(), raw()
                    else: r, n = raw(), native()
                    assert n['compiles'] == (count if case == 'cold' else 1 if case == 'leaf' else 0), (count, case, n['compiles'])
                    if case in ('cold', 'recovery'): assert r['compiles'] == count
                    if case in ('seeded', 'unchanged'): assert r['compiles'] == 0
                    raw_runtime = raw_src / name(count - 1) / 'bin/Release/net10.0'
                    assert n['runtimeHashes'] == hashes(raw_runtime), (count, case, 'runtime mismatch')
                    for label, directory in (('raw', raw_runtime), ('native', state / 'g/bazel-bin/build.bundle/app')):
                        result = command([DOTNET_ROOT / 'dotnet', directory / (name(count - 1) + '.dll')], base, base / (case + '-' + label + '-run.log'))
                        assert result.strip() == expected, (count, case, label, result, expected)
                    report['samples'].append(dict(count=count, repetition=rep, case=case, native=n, raw=r))
                    (output / 'report.json').write_text(json.dumps(report, indent=2))
                    print(count, rep, case, round(n['seconds'], 3), round(r['seconds'], 3), n['compiles'], r['compiles'], flush=True)
                shutdown(state)
        report['summary'] = []
        for count in counts:
            for case in ('cold', 'seeded', 'unchanged', 'leaf', 'recovery'):
                rows = [s for s in report['samples'] if s['count'] == count and s['case'] == case]
                native = statistics.median(s['native']['seconds'] for s in rows)
                raw = statistics.median(s['raw']['seconds'] for s in rows)
                report['summary'].append(dict(count=count, case=case, nativeMedian=native, rawMedian=raw, ratio=native/raw,
                    targetMet=native <= raw * 1.25 + .250 if case in ('unchanged', 'leaf') else None))
        report['accepted'] = True
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2))
        for state in states: shutdown(state)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--counts', type=int, nargs='+', default=[10, 100])
    parser.add_argument('--repetitions', type=int, default=3)
    args = parser.parse_args()
    if args.repetitions < 1: parser.error('positive repetitions required')
    measure(args.output.resolve(), args.counts, args.repetitions)
