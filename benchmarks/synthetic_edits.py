"""Check shared end-to-end timings against real raw/Bazel body and API edits."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.measure import command
from benchmarks.synthetic import prepare


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    output = a.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    workspace = prepare(output/'bazel', 4)
    raw = output/'raw'; shutil.copytree(workspace, raw)
    sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
    bazel = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base='+str(output/'base'), '--ignore_all_rc_files']
    records = []
    try:
        for engine, source in [('raw', raw), ('bazel', workspace)]:
            leaf = source/'P0/Value.cs'; original = leaf.read_text()
            try:
                for case in ['cold', 'noop', 'body', 'resource', 'api']:
                    if case == 'body':
                        leaf.write_text(original.replace('=> 1;', '=> 2;'))
                    if case == 'resource':
                        (source/'P0/Message.txt').write_text('changed')
                    if case == 'api':
                        leaf.write_text(original.replace('; }', '; public static int Added() => 3; }'))
                    log = output/(engine+'-'+case+'.log')
                    execution = output/(engine+'-'+case+'.execution.json')
                    argv = ([sdk/'dotnet', 'build', 'P3/P3.csproj', '-c', 'Release', '-m:2', '--nologo'] if engine == 'raw' else
                        [*bazel, 'build', '--jobs=2', '--disk_cache=', '--remote_cache=', '--execution_log_json_file='+str(execution), '//:benchmark'])
                    result, seconds = command(argv, source, log, timeout=600)
                    result.check_returncode()
                    reference = (source/'P0/obj/Release/net10.0/ref/P0.dll' if engine == 'raw' else source/'bazel-bin/P0/P0.reference/P0.dll')
                    implementation = (source/'P0/bin/Release/net10.0/P0.dll' if engine == 'raw' else source/'bazel-bin/P0/P0.runtime/P0.dll')
                    row = dict(engine=engine, case=case, wallSeconds=seconds, reference=digest(reference), implementation=digest(implementation))
                    if case == 'cold':
                        initial = row
                    if case in ['noop', 'body', 'resource']:
                        assert row['reference'] == initial['reference'], row
                    if case in ['body', 'resource']:
                        assert row['implementation'] != initial['implementation'], row
                    if case == 'resource':
                        assert row['implementation'] != previous['implementation'], row
                    if case == 'api':
                        assert row['reference'] != initial['reference'], row
                    if engine == 'bazel':
                        text = execution.read_text(); decoder = json.JSONDecoder(); actions = []
                        while text.strip():
                            action, end = decoder.raw_decode(text.lstrip()); text = text.lstrip()[end:]
                            if action.get('mnemonic') == 'MSBuildAssembly' and not action.get('cacheHit'):
                                actions.append(action['targetLabel'])
                        assert len(actions) == {'cold': 4, 'noop': 0, 'body': 1, 'resource': 1, 'api': 4}[case], (case, actions)
                        row['compiled'] = actions
                    previous = row
                    records.append(row)
                    (output/'results.json').write_text(json.dumps(records, indent=2)+'\n')
            finally:
                leaf.write_text(original)
                (source/'P0/Message.txt').write_text('original')
    finally:
        subprocess.run([*bazel, 'shutdown'], cwd=workspace, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([sdk/'dotnet', 'build-server', 'shutdown'], cwd=raw, stdout=subprocess.DEVNULL)
    print('Raw/Bazel body, resource and API timing controls passed')


if __name__ == '__main__':
    main()
