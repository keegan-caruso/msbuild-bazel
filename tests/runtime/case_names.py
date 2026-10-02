"""Normalize only reviewed nondeterministic runtime MemberData display values."""
from collections import Counter
import re

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
