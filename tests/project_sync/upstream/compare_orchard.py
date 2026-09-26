"""Compare the generated Orchard nodes and dependency edges with the authored graph."""
import ast
import json
from pathlib import Path
import sys

workspace, authored, report = [Path(arg).resolve() for arg in sys.argv[1:]]
old = json.loads(authored.read_text())
new = {}
for node in ast.walk(ast.parse((workspace / 'projects.generated.bzl').read_text())):
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id not in ['msbuild_project', 'msbuild_binary']:
        continue
    attrs = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
    assert attrs['project'] not in new
    if node.func.id == 'msbuild_project':
        assert len(attrs['target_frameworks']) == 1
        framework = attrs['target_frameworks'][0]
        attrs.update(attrs['framework_overrides'][framework], target_framework=framework)
    new[attrs['project']] = attrs
assert set(new) == set(old) and len(new) == 202
counts = {}
for field in ['deps', 'implementation_deps', 'analyzers', 'build_deps', 'tools', 'bindings']:
    for project, previous in old.items():
        assert set(previous.get(field, [])) == set(new[project].get(field, [])), (project, field)
    counts[field] = sum(len(set(attrs.get(field, []))) for attrs in new.values())
# The Web SDK adds an implicit ASP.NET reference. The generated provider exports
# it explicitly, so compare SDK evaluation rather than only authored attributes.
inventory = {row['project']: row for row in json.loads((authored.parent / 'graph.json').read_text())}
for project, attrs in new.items():
    expected = {item['include'] for item in inventory[project]['frameworks'] if item['include'] != 'Microsoft.NETCore.App' or item['metadata'].get('IsImplicitlyDefined', '').lower() != 'true'}
    assert set(attrs.get('framework_refs', [])) == expected, project
counts['framework_refs'] = sum(len(attrs.get('framework_refs', [])) for attrs in new.values())
for project, previous in old.items():
    assert set(previous['srcs']) == set(new[project]['srcs']) | set(new[project].get('source_paths', {})), project
    assert previous.get('package_private_assets', {}) == new[project].get('package_private_assets', {}), project
    assert new[project]['target_framework'] == previous['target_framework']
    assert new[project]['assembly_name'] == previous['assembly_name']
    assert new[project]['package_lock'].removeprefix('@@//') == previous['package_lock']
report.write_text(json.dumps(dict(projects=len(new), configuredNodesEqual=True, dependencyEdgesEqual=True, compileInputsEqual=True, packagePrivacyEqual=True, evaluatedFrameworkReferencesEqual=True, edges=counts), indent=2) + '\n')
print(report.read_text(), end='')
