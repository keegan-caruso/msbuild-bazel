"""Controlled, behavior-preserving edits shared by local and remote qualification."""
from contextlib import contextmanager
import re

@contextmanager
def edit(workspace, case):
    root=workspace/'upstream/src/libraries/System.Collections.Immutable'
    body=root/'src/System/Collections/Immutable/ImmutableArray.cs'
    contract=root/'ref/System.Collections.Immutable.cs'
    original_bytes={p:p.read_bytes() for p in [body,contract]}
    originals={p:data.decode('utf-8') for p,data in original_bytes.items()}
    try:
        if case=='body':
            before='return ImmutableArray<T>.Empty;'
            assert before in originals[body]
            text=originals[body].replace(before,'return QualificationIdentity(ImmutableArray<T>.Empty);',1)
            match=re.search(r'public static class ImmutableArray\s*\{',text)
            helper='\n        [MethodImpl(MethodImplOptions.NoInlining)]\n        private static ImmutableArray<T> QualificationIdentity<T>(ImmutableArray<T> value) => value;\n'
            body.write_text(text[:match.end()]+helper+text[match.end():])
        elif case in ['api','contract-only']:
            for path in ([contract] if case=='contract-only' else [body,contract]):
                text=originals[path]
                # Authored contract is a partial class; implementation is not.
                match=re.search(r'public static (?:partial )?class ImmutableArray\s*\{',text)
                assert match,path
                declaration='\n        /// <summary>Qualification API edit.</summary>\n        public static int BazelQualificationApi() '+('{ throw null; }' if path==contract else '=> 42;')+'\n'
                path.write_text(text[:match.end()]+declaration+text[match.end():])
        else:assert case=='baseline',case
        yield
    finally:
        for path,data in original_bytes.items():path.write_bytes(data)
