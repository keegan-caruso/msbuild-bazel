"""Check cached recovery, local launch and remote edits with reduced downloads.

Input is the completed remote_execution.py Bazel workspace. Every mode receives
its own source copy and fresh output base; the seeded remote instance is retained.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from remote_support import RemoteFixture

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('workspace', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--executor', required=True)
p.add_argument('--modes', nargs='+', choices=['all', 'toplevel', 'minimal'], default=['all', 'toplevel', 'minimal'])
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
target = '//:theme_test'
leaf = '//upstream:Avalonia.Remote.Protocol'
consumers = [target, leaf, '//upstream:Avalonia.Controls', '//upstream:Avalonia.Dialogs',
             '//upstream:Avalonia.Markup.Xaml', '//upstream:Avalonia.Themes.Simple']
for mode in a.modes:
    workspace = a.output / (mode + '-source')
    shutil.copytree(a.workspace, workspace, ignore=shutil.ignore_patterns('bazel-*'))
    f = RemoteFixture(a.output / mode, a.executor, workspace,
                      instance=(workspace / 'remote-instance.txt').read_text())
    f.sdk()
    def run(case, expected=(), **kwargs):
        return f.run(case, [target], [('MSBuildAssembly', label) for label in expected], downloads=mode, **kwargs)
    try:
        actions = run('recovery', tests=[])
        assert actions and all(x['cacheHit'] for x in actions)
        assert any(x['mnemonic'] == 'TestRunner' for x in actions)
        packages = list((f.base / 'execroot/_main/bazel-out').glob('*/bin/upstream/*.package/**/*.nupkg'))
        assert bool(packages) == (mode == 'all'), (mode, packages)
        (f.folder / 'materialization.json').write_text(json.dumps(dict(packageArchivesDownloaded=len(packages))))
        run('launch', command='run')
        assert 'SimpleTheme styles=1; protocol=remote-body-edit; api=42' in (f.folder / 'launch.log').read_text()
        source = workspace / 'upstream/src/Avalonia.Remote.Protocol/DefaultMessageTypeResolver.cs'
        original = source.read_text()
        assert 'remote-body-edit' in original
        identity = hashlib.sha256(str(a.output.resolve()).encode()).hexdigest()[:12]
        marker = 'download-' + mode + '-' + identity
        body = original.replace('remote-body-edit', marker)
        source.write_text(body)
        run('body', [leaf], tests=[target])
        log = workspace / 'bazel-testlogs/theme_test/test.log'
        assert 'protocol=' + marker + '; api=42' in log.read_text()
        old = 'public int RemoteQualificationMarker() => 42;'
        assert body.count(old) == 1
        source.write_text(body.replace(old, old + '\n public int Download' + mode.title() + identity + '() => 1;'))
        run('api', consumers, tests=[target])
        assert 'protocol=' + marker + '; api=42' in log.read_text()
    finally:
        f.shutdown()
