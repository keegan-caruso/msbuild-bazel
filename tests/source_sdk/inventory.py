"""Inventory pinned VMR build definitions; this is not an MSBuild evaluator.

Qualification tooling only. Source builds and production orchestration stay in
upstream MSBuild and Bazel. Conditions are retained verbatim for later evaluation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def repository_references(path):
    result = []

    def visit(element, conditions):
        conditions = conditions + ([element.attrib['Condition']] if 'Condition' in element.attrib else [])
        if element.tag == 'RepositoryReference':
            result.append({'attributes': dict(element.attrib), 'conditions': conditions,
                           'metadata': [{'name': c.tag, 'value': c.text or '',
                                         'attributes': dict(c.attrib)} for c in element]})
        for child in element:
            visit(child, conditions)

    visit(ET.parse(path).getroot(), [])
    return result


def inventory(source, pin):
    for name, expected in pin['definitionHashes'].items():
        actual = digest(source / name)
        if actual != expected:
            raise ValueError('Pinned definition changed: ' + name)
    manifest = json.loads((source / 'src/source-manifest.json').read_text())
    global_json = json.loads((source / 'global.json').read_text())
    return {
        'schemaVersion': 1,
        'sourceRevision': pin['sourceRevision'],
        'configuration': pin['configuration'],
        'bootstrap': global_json,
        'repositories': [dict(row, declaredReferences=repository_references(
            source / 'repo-projects' / (row['path'] + '.proj')))
                         for row in manifest['repositories']],
        'submodules': manifest['submodules'],
        'sharedReferenceOperations': repository_references(source / 'repo-projects/Directory.Build.targets'),
        'graphStatus': 'unevaluated declarations; do not use as a build graph',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    pin = json.loads(Path(__file__).with_name('pin.json').read_text())
    result = inventory(args.source, pin)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print('Inventoried', len(result['repositories']), 'repositories; conditions are unevaluated.')


if __name__ == '__main__':
    main()
