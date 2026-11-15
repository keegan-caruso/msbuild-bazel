"""Exercise the actual Starlark expansion with synthetic tree artifacts."""
import json
from pathlib import Path
import sys
import textwrap
from types import SimpleNamespace

source = (Path(__file__).resolve().parents[2] / 'msbuild/private/runtime_layout.bzl').read_text()
body = source.split('    def entries(file, expander):\n', 1)[1].split('\n    args =', 1)[0]
code = 'def entries(file, expander):\n' + textwrap.dedent(body).replace('\n', '\n    ').join(['    ', ''])
# Starlark statements in this callback are valid Python as well.
ns = {'json': SimpleNamespace(encode=json.dumps)}
exec(compile(code, 'runtime_layout.bzl', 'exec'), ns)
entries = ns['entries']


def run(projects, files):
    selections = [(f'workspace/p{i}/', f'A{i}.dll') for i in range(projects)]
    selections += [('workspace/p0/nested/', 'Nested.dll')]
    children = [f'workspace/p{i}/nested/f{j}.dat' for i in range(projects) for j in range(files)]
    ns.update(selections=selections, shared='shared/framework/1')
    expanded = [SimpleNamespace(path='tree/' + path) for path in children]
    expander = SimpleNamespace(expand=lambda _: expanded)
    probes = 0
    def trace(frame, event, arg):
        nonlocal probes
        if frame.f_code is entries.__code__ and event == 'line' and frame.f_lineno == 7:
            probes += 1
        return trace
    sys.settrace(trace)
    try:
        actual = [json.loads(x) for x in entries(SimpleNamespace(path='tree'), expander)]
    finally:
        sys.settrace(None)
    expected = []
    for prefix, assembly in selections:
        required = prefix + assembly
        expected.append({'source': 'tree/' + required, 'path': 'shared/framework/1/' + assembly})
        expected += [{'source': 'tree/' + path, 'path': 'shared/framework/1/' + path[len(prefix):]}
                     for path in children if path.startswith(prefix) and path != required]
    assert actual == expected
    return probes, len(children), len(selections)


small = run(100, 10)
large = run(1000, 10)
assert large[0] <= small[0] * 10 + 10, (small, large)
assert large[0] < large[1] * large[2] // 100, large
print('PASS: nested outputs and stable order; ancestor probes:', small, large)
