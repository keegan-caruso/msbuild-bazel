"""Known unstable display-name normalization for pinned Immutable theories."""
from collections import Counter

# Int32StringData deliberately shuffles with Guid.NewGuid(), so its four
# theory methods have unstable, truncated parameter displays. Preserve the
# per-method multiplicity/outcomes; compare every other case's full display.
shuffled={
    'System.Collections.Frozen.Tests.FrozenFromKnownValuesTests.FrozenDictionary_Int32String',
    'System.Collections.Frozen.Tests.FrozenFromKnownValuesTests.FrozenSet_Int32String',
    'System.Collections.Frozen.Tests.FrozenDictionaryAlternateLookupTests.AlternateLookup_Int32_AlternateKeyString',
    'System.Collections.Frozen.Tests.FrozenSetAlternateLookupTests.AlternateLookup_Int32_AlternateKeyString',
}
def normalized(rows):
    result=Counter()
    for (name,outcome),count in rows.items():
        method=name.split('(',1)[0]
        if method in shuffled:name=method
        elif method in ['System.Collections.Tests.DebugView_Tests.TestDebuggerAttributes_Null','System.Collections.Tests.DebugView_Tests.TestDebuggerAttributes_Dictionary']:
            name=name.replace('obj: [[b, B], [a, 1]]','obj: [[a, 1], [b, B]]')
        result[name,outcome]+=count
    return result
