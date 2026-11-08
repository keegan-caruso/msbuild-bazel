"""Compare qualification Restore reuse using actual runtime body/API edits.

Use an owned, fully prepared runtime source workspace with qualification_cache.
Bazel action caches are disabled; HTTP project snapshots remain enabled. Each
mode uses a distinct, equivalent edit so one cannot consume the other's results.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--mappings', required=True, help='workspace-relative mapping used by //:sync')
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--cache-url', required=True)
    parser.add_argument('--repo-contents-cache', type=Path)
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--profile', action='store_true', help='diagnostics only; leave off for scored pairs')
    parser.add_argument('--trim-between-rows', action='store_true', help='trim the disposable guest outside measured intervals; requires permission to run fstrim')
    parser.add_argument('--mode', choices=['both', 'baseline', 'candidate'], default='both')
    args = parser.parse_args()
    assert args.samples > 0 and os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    root, results, base = args.workspace.resolve(), args.results.resolve(), args.output_base.resolve()
    assert not results.exists() and not base.exists()
    assert not results.is_relative_to(root) and not base.is_relative_to(root)
    assert 'qualification_cache=True' in (root/'BUILD.bazel').read_text().replace(' ', '')
    mappings = (root/args.mappings).resolve(strict=True)
    assert mappings.is_relative_to(root)
    edit = json.loads((ROOT/'tests/graph_build/upstream/runtime_source_host_edit.json').read_text())
    paths = {name: root/edit[name] for name in ['implementation', 'reference']}
    originals = {path: path.read_bytes() for path in [mappings, *paths.values()]}
    settings = json.loads(originals[mappings])
    outputs = ['graph.generated.json', 'graph.generated.bzl']
    expected = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in outputs}
    contract = json.loads((root/'graph.generated.json').read_text())
    count = sum(bool(node['OutputDirectories'] or node.get('OutputFiles')) for project in contract['Projects'].values()
        for node in project.get('Configurations') or [project])
    modes = ['baseline', 'candidate'] if args.mode == 'both' else [args.mode]
    results.mkdir(parents=True)
    command = [str(ROOT/'scripts/bazel-launcher.sh'), '--nosystem_rc', '--nohome_rc', '--noworkspace_rc',
        '--output_base='+str(base)]
    options = ['run', '//:sync', '--jobs=1', '--disk_cache=', '--remote_cache=',
        '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL='+args.cache_url,
        '--action_env=RULES_MSBUILD_SYNC_PROFILE='+('1' if args.profile else '0'), '--noshow_progress']
    if args.repo_contents_cache:
        options += ['--repo_contents_cache='+str(args.repo_contents_cache.resolve())]
    if os.environ.get('RULES_MSBUILD_TEST_REPOSITORY_CACHE'):
        options += ['--repository_cache='+os.environ['RULES_MSBUILD_TEST_REPOSITORY_CACHE']]
    rows = []

    def run(mode, case, sample):
        mapping = dict(settings, restoreReuseInputs=sorted(edit[key] for key in paths) if mode == 'candidate' else [])
        mappings.write_text(json.dumps(mapping, indent=2)+'\n')
        log = results/(mode+'-'+case+'-'+str(sample)+'.log')
        start = time.monotonic()
        with log.open('w') as stream:
            subprocess.run(command+options, cwd=root, stdout=stream, stderr=subprocess.STDOUT, check=True)
        seconds = time.monotonic()-start
        text = log.read_text()
        cache = json.loads(re.findall(r'^PROJECT_SYNC_CACHE (\{[^\n]+\})', text, re.M)[-1])
        restore = re.findall(r'^PROJECT_SYNC_RESTORE_CACHE (hit|miss)$', text, re.M)[-1]
        assert cache['hits']+cache['misses'] == count and cache['uncacheable'] == 0, cache
        assert {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in outputs} == expected
        if case in ['body', 'api']:
            assert 0 < cache['compilations'] < count, cache
            assert restore == ('hit' if mode == 'candidate' else 'miss'), (mode, case, restore)
        if case == 'restored':
            assert cache['compilations'] == 0 and restore == 'hit', cache
        phases = [json.loads(line) for line in re.findall(r'^PROJECT_SYNC_PROFILE (\{[^\n]+\})', text, re.M)]
        row = dict(mode=mode, case=case, sample=sample, seconds=seconds, cache=cache, restore=restore,
            profiled=args.profile, phases=phases)
        rows.append(row)
        (results/'results.json').write_text(json.dumps(dict(command=command+options, rows=rows), indent=2)+'\n')
        print(json.dumps({key: value for key, value in row.items() if key != 'phases'}), flush=True)
        if args.trim_between_rows:
            subprocess.run(['fstrim', '/'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    try:
        for mode in modes:
            run(mode, 'seed', -1)
        for sample in range(args.samples):
            for case in ['body', 'api']:
                for mode in modes if sample % 2 == 0 else modes[::-1]:
                    for path in paths.values():
                        path.write_bytes(originals[path])
                    token = uuid.uuid4().hex
                    if case == 'body':
                        value = originals[paths['implementation']]
                        anchor = edit['bodyAnchor'].encode()
                        assert value.count(anchor) == 1
                        paths['implementation'].write_bytes(value.replace(anchor,
                            anchor+b'\n            GC.KeepAlive("qualification-'+token.encode()+b'");'))
                    else:
                        for name in paths:
                            value = originals[paths[name]]
                            anchor = edit[name+'Anchor'].encode()
                            assert value.count(anchor) == 1
                            method = '\n        public static string Qualification_'+token+'() => "'+token+'";'
                            paths[name].write_bytes(value.replace(anchor, anchor+method.encode()))
                    run(mode, case, sample)
        for path in paths.values():
            path.write_bytes(originals[path])
        run(modes[-1], 'restored', -1)
        for case in ['body', 'api']:
            assert len({row['cache']['compilations'] for row in rows if row['case'] == case}) == 1
        medians = {mode: {case: statistics.median(row['seconds'] for row in rows
            if row['mode'] == mode and row['case'] == case) for case in ['body', 'api']} for mode in modes}
        (results/'medians.json').write_text(json.dumps(medians, indent=2)+'\n')
        print(json.dumps(medians), flush=True)
    finally:
        for path, data in originals.items():
            path.write_bytes(data)
        subprocess.run(command+['shutdown'], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
