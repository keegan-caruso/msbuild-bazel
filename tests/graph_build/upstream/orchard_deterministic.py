"""Qualify a disposable Orchard API edit with an explicitly patched generator."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import upstream_edits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('contract', type=Path)
    parser.add_argument('cache', type=Path)
    parser.add_argument('results', type=Path)
    args = parser.parse_args()
    source = args.workspace / 'src/OrchardCore/OrchardCore.SourceGenerators/ArgumentsFromInterceptor.cs'
    original = source.read_bytes()
    stamp = source.stat()
    needle = b'var uniqueId = Guid.NewGuid().ToString("N");'
    assert original.count(needle) == 1
    patch = b'using var hash = System.Security.Cryptography.SHA256.Create();\n        var uniqueId = string.Concat(hash.ComputeHash(Encoding.UTF8.GetBytes(info.Location.Version + ":" + info.Location.Data)).Select(value => value.ToString("x2")));'
    try:
        source.write_bytes(original.replace(needle, patch))
        args.results.mkdir(parents=True, exist_ok=True)
        (args.results / 'qualification-patch.json').write_text(json.dumps(dict(
            path=str(source.relative_to(args.workspace)), originalSha256=hashlib.sha256(original).hexdigest(),
            patchedSha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            purpose='Isolate upstream generator nondeterminism; not an unmodified-upstream qualification'))+'\n')
        sys.argv = ['upstream_edits', str(args.workspace), str(args.contract), str(args.cache),
                    str(Path(__file__).with_name('orchard_edits.json')), str(args.results), '--only', 'api', '--profile']
        upstream_edits.main()
        row = json.loads((args.results / 'summary.json').read_text())[0]
        assert not row['missing'] and not row['extra'], row
        assert all(path.endswith(('/rjsmcshtml.dswa.cache.json', '/rjsmrazor.dswa.cache.json')) for path in row['changed']), row['changed']
        print('PASS: deterministic qualification patch gives exact assembly/PDB parity; remaining JSON differences retained for inspection')
    finally:
        source.write_bytes(original)
        os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))


if __name__ == '__main__':
    main()
