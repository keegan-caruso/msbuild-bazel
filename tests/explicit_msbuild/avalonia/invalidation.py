"""Exact edit/revert action contracts for an already-qualified expanded workspace."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from remote_support import RemoteFixture
from suite_support import serialize, test_outcomes

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('workspace', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--executor', required=True)
p.add_argument('--instance', help='Producer cache namespace; defaults to the copied manifest')
a = p.parse_args()
workspace = a.workspace.resolve()
saved = json.loads((workspace / 'expanded-qualification.json').read_text())
f = RemoteFixture(a.output, a.executor, workspace, instance=a.instance or saved['instance'])
f.sdk()
root = workspace / 'upstream'
targets = saved['targets']
suites = sorted(saved['outcomes'])
variant = hashlib.sha256(a.output.name.encode()).hexdigest()[:6]
originals = {}
evidence = []


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parity():
    for suite in suites:
        assert serialize(test_outcomes(workspace, suite)) == saved['outcomes'][suite], suite


def edit(case, path, replacement, expected, tests, *, error=None, changed_output=None, reference=None, reference_changes=False):
    original = path.read_bytes()
    originals[path] = original
    before = digest(changed_output) if changed_output else None
    ref_before = digest(reference) if reference else None
    assert original != replacement
    try:
        path.write_bytes(replacement)
        f.run(case, targets, expected, tests=sorted(tests), error=error)
        if changed_output:
            assert digest(changed_output) != before, (case, 'output did not change')
        if reference:
            assert (digest(reference) != ref_before) == reference_changes, (case, 'unexpected reference change')
        if error:
            failures = {suite: sum(count for (_, outcome), count in test_outcomes(workspace, suite).items() if outcome == 'Failed') for suite in suites if '//upstream:'+suite in tests}
            assert any(failures.values()), (case, failures)
            (f.folder/(case+'-outcomes.json')).write_text(json.dumps({suite:serialize(test_outcomes(workspace,suite)) for suite in failures},indent=2)+'\n')
        else:
            parity()
        evidence.append(dict(case=case,input=path.relative_to(workspace).as_posix(),before=hashlib.sha256(original).hexdigest(),after=digest(path),negativeControl=bool(error),outputChanged=bool(changed_output),referenceChanged=reference_changes if reference else None))
    finally:
        path.write_bytes(original)
    f.run(case + '-restored', targets, [], tests=[], downloads='toplevel')
    parity()


try:
    actions = f.run('baseline-recovery', targets, [], tests=[])
    assert actions and all(x['cacheHit'] for x in actions)
    parity()
    path = root / 'src/Avalonia.Native/avn.idl'
    original = path.read_bytes()
    assert original.count(b'AvnKeyNone = 0,') == 1
    edit('idl-edit', path, original.replace(b'AvnKeyNone = 0,', ('AvnKeyNone = -' + str(int(variant,16)) + ',').encode()),
         [('MSBuildGenerate','//upstream:desktop_idl_4'),('MSBuildAssembly','//upstream:Avalonia.Native'),('MSBuildAssembly','//upstream:Avalonia.Desktop')], [],
         changed_output=workspace/'bazel-bin/upstream/desktop_idl_4.generated/Interop.Generated.cs',
         reference=workspace/'bazel-bin/upstream/Avalonia.Native.reference/Avalonia.Native.dll', reference_changes=True)
    path = root / 'src/Avalonia.Themes.Simple/Controls/Button.xaml'
    original = path.read_bytes()
    assert original.count(b'  <ControlTheme ') == 1
    # Both variants are deliberately present in the pinned combined fixture.
    theme_labels = ['Avalonia.Themes.Simple_net8_0_0caeea827ca4','Avalonia.Themes.Simple_netstandard2_0_b4ab3a281b90']
    edit('xaml-resource-edit', path, original.replace(b'  <ControlTheme ', ('  <Color x:Key="QualificationMarker'+variant+'">#010203</Color>\n  <ControlTheme ').encode()),
         [('MSBuildAssembly','//upstream:'+label) for label in theme_labels], ['//upstream:'+s for s in suites],
         changed_output=workspace/('bazel-bin/upstream/'+theme_labels[0]+'.runtime/Avalonia.Themes.Simple.dll'),
         reference=workspace/('bazel-bin/upstream/'+theme_labels[0]+'.reference/Avalonia.Themes.Simple.dll'))
    path = root / 'tests/TestFiles/Skia/OpacityMask/Opacity_Mask_Masks_Element.expected.png'
    edit('baseline-negative', path, ('qualification-invalid-png-'+variant).encode(), [], ['//upstream:Avalonia.Skia.RenderTests'], error='FAILED')
    path = root / 'native-tests/libfontconfig.so.1'
    edit('native-negative', path, ('qualification-invalid-library-'+variant).encode(), [],
         ['//upstream:Avalonia.Skia.UnitTests','//upstream:Avalonia.Skia.RenderTests'], error='FAILED')
    (f.folder/'invalidation.json').write_text(json.dumps(evidence,indent=2)+'\n')
finally:
    for path, original in originals.items():
        path.write_bytes(original)
    f.shutdown()
