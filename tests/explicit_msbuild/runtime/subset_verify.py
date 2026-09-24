"""Compare all selected upstream cases and independently verify loaded producers."""
from collections import Counter
import hashlib
import json
import re
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile

workspace,raw,report=[Path(p).resolve() for p in sys.argv[1:]]
manifest=json.loads((workspace/'subset.json').read_text())
shuffled={
 'System.Collections.Frozen.Tests.FrozenFromKnownValuesTests.FrozenDictionary_Int32String',
 'System.Collections.Frozen.Tests.FrozenFromKnownValuesTests.FrozenSet_Int32String',
 'System.Collections.Frozen.Tests.FrozenDictionaryAlternateLookupTests.AlternateLookup_Int32_AlternateKeyString',
 'System.Collections.Frozen.Tests.FrozenSetAlternateLookupTests.AlternateLookup_Int32_AlternateKeyString',
}
def normalize(rows):
    result=Counter()
    for (name,outcome),count in rows.items():
        method=name.split('(',1)[0]
        if method in shuffled:name=method
        elif method in ['System.Collections.Tests.DebugView_Tests.TestDebuggerAttributes_Null','System.Collections.Tests.DebugView_Tests.TestDebuggerAttributes_Dictionary']:
            name=name.replace('obj: [[b, B], [a, 1]]','obj: [[a, 1], [b, B]]')
        # These upstream MemberData values call GetHashCode in the current
        # process. Preserve method, generic type and value; omit only the seed.
        if method in {
            'System.Collections.Generic.Tests.EqualityComparerTests.GetHashCodeTest<Object>',
            'System.Collections.Generic.Tests.EqualityComparerTests.GetHashCodeTest<String>',
            'System.Collections.Generic.Tests.EqualityComparerTests.GetHashCodeTest<NonEquatableValueType>',
            'System.Collections.Generic.Tests.EqualityComparerTests.NullableGetHashCode<NonEquatableValueType>',
            'System.Collections.Tests.StructuralComparisonsTests.StructuralEqualityComparer_GetHashCode',
        }:
            name=re.sub(r'expected: -?\d+\)$','expected: <process hash>)',name)
        if method=='System.Threading.Tasks.Tests.TaskAwaiterTests.OperationCanceledException_PropagatesThroughCanceledTask':
            # Upstream uses CallerLineNumber to identify each of its 14 cases.
            # Live Task.Status and exception stack text race with execution.
            match=re.match(r'.*\(lineNumber: (\d+), task:',name)
            assert match,name
            name=method+'(lineNumber: '+match.group(1)+')'
        if method in {'System.Threading.Tests.MutexTests.Ctor_ValidName','System.Threading.Tests.MutexTests.AbandonExisting','System.Threading.Tests.MutexTests.OpenExisting'}:
            name=re.sub(r'name: "[0-9a-f]{32}"', 'name: "<unique mutex>"',name)
        cls,_,member=method.rpartition('.')
        # These four file-copy subclasses share File/Copy.cs MemberData.
        if cls in {'System.IO.Tests.'+c for c in ['FileInfo_CopyTo_str_b','FileInfo_CopyTo_str','File_Copy_str_str_b','File_Copy_str_str']} and member=='CopyFileWithData':
            payload=name.split('data: [',1)[1].rsplit('], readOnly:',1)[0]
            if payload.endswith('···'):shape='truncated'
            else:
                tokens=re.findall(r"0x[0-9a-f]+|'(?:\\.|[^'\\])*'",payload)
                assert ', '.join(tokens)==payload,payload
                shape=str(len(tokens))
            name=name.split('data: [',1)[0]+'data: <random '+shape+' characters>, readOnly:'+name.rsplit('], readOnly:',1)[1]
        if cls in {'System.IO.Tests.'+c+'FileStreamStandaloneConformanceTests' for c in ['BufferedAsync','BufferedSync','UnbufferedAsync','UnbufferedSync']} and member=='CopyTo_CopiesAllDataFromRightPosition_Success':
            name=re.sub(r'expected: \[.*?\]', 'expected: <random bytes>',name)
        path_classes={'System.IO.Tests.'+c for c in ['CreateDirectoryWithUnixFileMode','DirectoryInfo_CreateSubDirectory','DirectoryInfo_Create','Directory_CreateDirectory']}
        exists_classes={'System.IO.Tests.'+c for c in ['File_Exists','Directory_Exists','PathFile_Exists','PathDirectory_Exists']}
        if (cls in path_classes and member in ['ValidPathWithTrailingSlash','ValidPathWithoutTrailingSlash']) or (cls in exists_classes and member in ['ValidPathExists_ReturnsTrue','NonExistentValidPath_ReturnsFalse']):
            name=re.sub(r'"[a-z0-9]{8}\.[a-z0-9]{3}"','"<random path component>"',name)
        result[name,outcome]+=count
    return result

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest().upper()
expected={}
for scope in ['managed','private']:
    for name,label in manifest.get(scope,{}).items():
        package,target=label.removeprefix('//').split(':');path=workspace/'bazel-bin'/package/(target+'.runtime')/name
        expected.setdefault(name,set()).add(sha(path))
for name,label in manifest['native'].items():
    package,_=label.removeprefix('//').split(':')
    expected.setdefault(name,set()).add(sha(workspace/'bazel-bin'/package/'runtime.generated'/name))
installed={}
for name,paths in json.loads((workspace/'runtime/runtime-inventory.json').read_text()).items():
    if name not in manifest['installed']:continue
    installed[name]={sha(workspace/'runtime'/p) for p in paths if (workspace/'runtime'/p).is_file()}
results=[];all_observed=set()
for test in manifest['tests']:
    name=test['assembly'];package,target=test['label'].removeprefix('//').split(':')
    logs=workspace/'bazel-testlogs'/package/target
    ns={'t':'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
    control=Counter((r.get('testName'),r.get('outcome')) for r in ET.parse(raw/name/'results/results.trx').getroot().findall('.//t:UnitTestResult',ns))
    cases=Counter((r.get('name'),'Failed' if r.find('failure') is not None or r.find('error') is not None else 'NotExecuted' if r.find('skipped') is not None else 'Passed') for r in ET.parse(logs/'test.xml').getroot().findall('.//testcase'))
    assert normalize(cases)==normalize(control),(name,normalize(cases)-normalize(control),normalize(control)-normalize(cases))
    assert not any(outcome=='Failed' for _,outcome in cases),(name,cases)
    output=logs/'test.outputs';proofs=[json.loads(p.read_text()) for p in output.glob('runtime-*.json')]
    if (output/'outputs.zip').exists():
        with zipfile.ZipFile(output/'outputs.zip') as archive:proofs += [json.loads(archive.read(n)) for n in archive.namelist() if n.startswith('runtime-') and n.endswith('.json')]
    raw_proofs=[json.loads(p.read_text()) for p in (raw/name/'proof').glob('runtime-*.json')]
    process_entries=Counter(p['entry'] for p in proofs)
    assert process_entries==Counter(p['entry'] for p in raw_proofs),(name,process_entries,Counter(p['entry'] for p in raw_proofs))
    hosts=[p for p in proofs if p['entry']=='testhost'];assert hosts,(name,proofs)
    observed={}
    for proof in proofs:
        required={'System.Private.CoreLib.dll','libcoreclr.so','libclrjit.so'}
        required.update({'dotnet','libhostfxr.so','libhostpolicy.so'} & set(manifest['native']))
        assert required<=set(proof['files']),(name,proof)
        for file,row in proof['files'].items():
            if file in expected:
                assert row['sha256'] in expected[file] | installed.get(file,set()),(name,file,row,expected[file])
                if row['sha256'] in expected[file]:
                    observed[file]=row['sha256'];all_observed.add(file)
    results.append({'assembly':name,'cases':sum(cases.values()),'passed':sum(c for (_,o),c in cases.items() if o=='Passed'),'skipped':sum(c for (_,o),c in cases.items() if o=='NotExecuted'),'exactNamesMatch':cases==control,'normalizedNamesAndOutcomesMatch':True,'processEntries':dict(process_entries),'observedRebuilt':observed,'proofs':proofs})
report.write_text(json.dumps({'tests':results,'observedRebuilt':sorted(all_observed),'declaredButNotObserved':sorted(set(expected)-all_observed),'installedComponents':manifest['installed']},indent=2)+'\n')
print(json.dumps([{k:v for k,v in r.items() if k not in ['proofs','observedRebuilt']} for r in results]),flush=True)
