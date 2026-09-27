"""Compare SDK payload bytes and modes independently of tar/gzip metadata."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tarfile


def payload(path):
    result = {}
    with tarfile.open(path, 'r|gz') as archive:
        for entry in archive:
            name = entry.name.removeprefix('./')
            if entry.isdir():
                continue
            if name in result:
                raise ValueError('Duplicate SDK archive entry: ' + name)
            if entry.isfile():
                digest = hashlib.sha256()
                with archive.extractfile(entry) as content:
                    for block in iter(lambda: content.read(1024 * 1024), b''):
                        digest.update(block)
                value = {'sha256': digest.hexdigest(), 'bytes': entry.size}
            elif entry.issym() or entry.islnk():
                value = {'link': entry.linkname, 'hardLink': entry.islnk()}
            else:
                raise ValueError('Unsupported SDK archive entry: ' + name)
            result[name] = dict(value, mode=entry.mode)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('first', type=Path)
    p.add_argument('second', type=Path)
    p.add_argument('report', type=Path)
    a = p.parse_args()
    first, second = payload(a.first), payload(a.second)
    changed = sorted(name for name in first.keys() & second.keys() if first[name] != second[name])
    result = {'firstFiles': len(first), 'secondFiles': len(second),
              'unchangedFiles': sum(first[name] == second[name] for name in first.keys() & second.keys()),
              'added': sorted(second.keys() - first.keys()), 'removed': sorted(first.keys() - second.keys()),
              'changed': changed, 'changedExtensions': dict(Counter(Path(name).suffix for name in changed)),
              'byteIdenticalPayload': first == second}
    a.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value if key not in ['added', 'removed', 'changed'] else len(value)
                      for key, value in result.items()}, indent=2))


if __name__ == '__main__':
    main()
