"""Verify upstream case parity and actual loaded assemblies for an Immutable run."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile

workspace, raw, report = map(lambda p: Path(p).resolve(), sys.argv[1:])
name='src_libraries_System.Collections.Immutable_tests_System.Collections.Immutable.Tests_net10.0'
implementation=workspace/'bazel-bin/upstream/src_libraries_System.Collections.Immutable_src_System.Collections.Immutable_net10.0.runtime/System.Collections.Immutable.dll'
expected=hashlib.sha256(implementation.read_bytes()).hexdigest().upper()
ns={'t':'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
raw_cases=Counter((t.get('testName'),t.get('outcome')) for t in ET.parse(raw/'results/results.trx').getroot().findall('.//t:UnitTestResult',ns))
testlog=workspace/'bazel-testlogs/upstream'/name
cases=Counter((t.get('name'),'Failed' if t.find('failure') is not None or t.find('error') is not None else 'NotExecuted' if t.find('skipped') is not None else 'Passed') for t in ET.parse(testlog/'test.xml').getroot().findall('.//testcase'))
from case_names import normalized, shuffled
assert normalized(cases)==normalized(raw_cases),(normalized(cases)-normalized(raw_cases),normalized(raw_cases)-normalized(cases))
assert sum(cases.values())==22544 and all(outcome=='Passed' for _,outcome in cases)
proofs={}
for label,folder,entry in [('upstream',testlog,'testhost'),('smoke',workspace/'bazel-testlogs/smoke/smoke','Smoke')]:
    output=folder/'test.outputs'
    records=[json.loads(p.read_text()) for p in output.glob('loaded-immutable-*.json')]
    if (output/'outputs.zip').is_file():
        with zipfile.ZipFile(output/'outputs.zip') as archive:
            records += [json.loads(archive.read(n)) for n in archive.namelist() if n.startswith('loaded-immutable-') and n.endswith('.json')]
    assert records and all(p['entry']==entry and p['sha256']==expected for p in records),(label,records,expected)
    proofs[label]=records
result=dict(testCount=sum(cases.values()),exactDisplayNamesMatch=cases==raw_cases,normalizedCaseNamesAndOutcomesMatch=True,shuffledTheoryCases=sum(count for (name,_),count in cases.items() if name.split('(',1)[0] in shuffled),implementationSha256=expected,loadedAssemblyProofs=proofs,nativeRuntime='installed Microsoft.NETCore.App/10.0.11',sourceBuiltCoreCLR=False)
report.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
