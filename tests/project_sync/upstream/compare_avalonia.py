"""Compare the 53 generated Avalonia configurations to the authored inventory."""
import ast
import json
from pathlib import Path
import sys

prepared,w,report=[Path(p).resolve() for p in sys.argv[1:]]
old={}
for line in (prepared/'bazel/upstream/BUILD.bazel').read_text().splitlines():
    if not line.startswith(('msbuild_library(','msbuild_binary(')):continue
    call=ast.parse(line).body[0].value;a={k.arg:ast.literal_eval(k.value) for k in call.keywords}
    old[('upstream/'+a['project'],a['target_framework'])]=a
new={}
for call in ast.walk(ast.parse((w/'projects.generated.bzl').read_text())):
    if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Name) or call.func.id not in ['msbuild_project','msbuild_test_project']:continue
    a={k.arg:ast.literal_eval(k.value) for k in call.keywords}
    for tfm,values in a['framework_overrides'].items():new[(a['project'],tfm)]={**a,**values}
assert set(old)==set(new) and len(new)==53
edges={}
for field in ['deps','implementation_deps','analyzers','build_deps','tools','bindings']:
    for key,previous in old.items():
        assert set(previous.get(field,[]))==set(new[key].get(field,[])),(key,field)
    edges[field]=sum(len(set(v.get(field,[]))) for v in new.values())
for key,previous in old.items():
    actual=new[key]
    assert previous['assembly_name']==actual['assembly_name'],key
    assert previous['package_lock']==actual['package_lock'].removeprefix('@@//'),key
    assert previous['package_private_assets']==actual['package_private_assets'],key
    before={value if value.startswith(':') else 'upstream/'+value for value in previous['srcs']}
    after=set(actual['srcs'])|{label.removeprefix('@@//') for label in actual['source_paths']}
    assert before==after,(key,sorted(before-after),sorted(after-before))
# Package-produced AdditionalFiles must remain explicit even though sync does
# not execute package targets. Ignore unused None bookkeeping from the inventory.
def item_records(path, prefix=''):
    result={}
    for call in ast.walk(ast.parse(path.read_text())):
        if isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='msbuild_items':
            attrs={k.arg:ast.literal_eval(k.value) for k in call.keywords}
            result[':'+attrs['name']]=(attrs['item_type'],{prefix+p for p in attrs.get('srcs',[])},attrs.get('metadata',{}))
    return result
before_items=item_records(prepared/'bazel/upstream/BUILD.bazel','upstream/')
after_items={**item_records(w/'BUILD.bazel'),**item_records(w/'projects.generated.bzl')}
for key,previous in old.items():
    for label in previous.get('items',[]):
        kind,paths,metadata=before_items[label]
        if kind=='None':continue
        candidates=[after_items[label] for label in new[key].get('items',[]) if label in after_items]
        assert any(k==kind and p==paths and all(m.get(name)==value for name,value in metadata.items()) for k,p,m in candidates),(key,kind,paths,metadata)
    for kind in ['EmbeddedResource','AdditionalFiles','AvaloniaResource','AvaloniaXaml']:
        before_order=[sorted(before_items[label][1]) for label in previous.get('items',[]) if before_items[label][0]==kind]
        after_order=[sorted(after_items[label][1]) for label in new[key].get('items',[]) if label in after_items and after_items[label][0]==kind]
        assert before_order==after_order,(key,kind,'item order',before_order,after_order)
report.write_text(json.dumps(dict(configuredNodes=53,projectPaths=40,configuredNodesEqual=True,dependencyEdgesEqual=True,compileInputsEqual=True,packagePrivacyEqual=True,compilerItemInputsEqual=True,compilerItemOrderEqual=True,edges=edges),indent=2)+'\n')
print(report.read_text(),end='')
