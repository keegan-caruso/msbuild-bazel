"""Materialize locked native runtime inputs through a fixture-owned Bazel repository."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def register(workspace):
    lock = workspace / 'native-packages.json'
    if not lock.exists():
        return
    module = workspace / 'MODULE.bazel'
    text = module.read_text()
    assert 'native_runtime = use_repo_rule' not in text
    include = json.loads(lock.read_text()).get('include_vnc', False)
    module.write_text(text + '\nnative_runtime = use_repo_rule("//:native_packages.bzl", "native_runtime")\n' +
                      'native_runtime(name="avalonia_native", lock="//:native-packages.json", include_vnc=' + str(include) + ')\n')


def acquire(prepared, fixture):
    """Raw controls consume exactly the files declared to remote tests."""
    workspace = prepared / 'bazel'
    source = Path(__file__).parent
    inventory = json.loads((prepared / 'inventory.json').read_text())
    include = any('Avalonia.Headless.Vnc' in row['project'] for row in inventory)
    lock = json.loads((source / 'native-packages.json').read_text())
    lock['include_vnc'] = include
    (workspace / 'native-packages.json').write_text(json.dumps(lock, indent=2) + '\n')
    shutil.copyfile(source / 'native_packages.bzl', workspace / 'native_packages.bzl')
    (workspace / 'BUILD.bazel').touch(exist_ok=True)
    register(workspace)
    # Fetching file labels performs repository acquisition, not build actions.
    command = [fixture.bazel, '--output_base=' + str(fixture.base), '--ignore_all_rc_files',
               'fetch', '@avalonia_native//:runtime_files', '--lockfile_mode=off']
    with (fixture.folder / 'native-acquisition.log').open('w') as log:
        subprocess.run(command, cwd=workspace, stdout=log, stderr=subprocess.STDOUT, check=True)
    candidates = list((fixture.base / 'external').glob('*+avalonia_native'))
    assert len(candidates) == 1, candidates
    repository = candidates[0]
    root = prepared / 'native-tests'
    for row in lock['files']:
        for directory in [root, workspace / 'upstream/native-tests']:
            previous = directory / row['destination']
            if previous.is_file():
                previous.unlink()
    declarations = {}
    for row in lock['files']:
        if row.get('vnc_only') and not include:
            continue
        path = repository / row['destination']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256'], row['destination']
        target = root / row['destination']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        declarations['@avalonia_native//:' + row['destination']] = 'tests/native-tests/' + row['destination']
    return root, declarations
