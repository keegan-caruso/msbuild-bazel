"""A controller mutation after staging must reject project-cache publication."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import native_workflow
from native_workflow import Workflow, ROOT, BAZEL
from probe_native_workflow import fixture, TESTS
from probe_serilog_tests import PROJECT

parser = argparse.ArgumentParser(description=__doc__)
for key in ('source', 'packages', 'output'): parser.add_argument('--' + key, type=Path, required=True)
a = parser.parse_args(); out = a.output.resolve(); out.mkdir()
s = fixture(a.source, a.packages, out / 's'); state = out / 'state'
w = Workflow(s, state, PROJECT, tests=TESTS, reuse=True)
sentinel = ROOT / 'tools/ReplayPlugin/invocation-control.probe'
if sentinel.exists(): raise FileExistsError(sentinel)
try:
    w.run(out / 'cold', operation='test', force_tests=True)
    pointer = (state / 'cache.json').read_bytes()
    actual_generate = native_workflow.generate
    def mutate(*args, **kwargs):
        result = actual_generate(*args, **kwargs)
        sentinel.write_bytes(b'controller namespace changed after staging')
        return result
    with patch('native_workflow.generate', side_effect=mutate):
        try: w.run(out / 'mutation', operation='test', force_tests=True)
        except ValueError as error: assert 'controller inputs changed during consumption' in str(error), str(error)
        else: raise AssertionError('controller mutation was accepted')
    assert (state / 'cache.json').read_bytes() == pointer
    report = json.loads((out / 'mutation/report.json').read_text())
    assert not report['accepted'] and report['test']['passed'] and report['testActions'] == 1
    (out / 'report.json').write_text(json.dumps(dict(accepted=True, actualTestPassed=True, publicationChanged=False)))
finally:
    sentinel.unlink(missing_ok=True)
    subprocess.run([str(BAZEL), '--nohome_rc', '--noworkspace_rc', '--output_base=' + str(state / 'b'),
        '--output_user_root=' + str(state / 'u'), 'shutdown'], cwd=state / 'g', check=True)
