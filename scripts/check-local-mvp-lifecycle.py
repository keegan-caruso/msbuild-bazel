"""Check that the legacy fixture adapter rejects unsupported lifecycle operations."""
import json
from pathlib import Path
import subprocess
import sys

state = Path(sys.argv[1]).resolve()
root = state / 'lifecycle'
root.mkdir()
repo = Path(__file__).resolve().parents[1]
report = dict(accepted=False, cases={})
try:
    for operation in ('Clean', 'Rebuild', 'Pack', 'Publish'):
        output, request = root / operation, root / (operation + '.json')
        request.write_text(json.dumps(dict(schemaVersion=1, operation=operation,
            workspace=str(state / 'small'), output=str(output), configuration='Release')))
        result = subprocess.run([sys.executable, str(repo / 'tools/adapter.py'), '--request', str(request)],
            capture_output=True, text=True, timeout=30)
        assert result.returncode != 0 and result.stderr.strip() == 'unsupported operation' and not output.exists(), result
        report['cases'][operation] = dict(rejected=True, exitCode=result.returncode,
            diagnostic=result.stderr.strip(), outputAbsent=True)
    report['accepted'] = True
finally:
    (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
