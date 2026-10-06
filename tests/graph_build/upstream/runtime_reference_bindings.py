"""Bind the pinned raw Build's SDK-selected compiler/copy products for public sync.

Qualification only: review the emitted contracts before reuse. This does not infer
arbitrary custom-task reads or change upstream compilation/reference selection.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path, PurePosixPath

PREFIX = '/__rules_msbuild_graph/output/workspace/'


def relative(path):
    assert path.startswith(PREFIX), ('External runtime product', path)
    value = path.removeprefix(PREFIX)
    assert value and all(p not in ['', '.', '..'] for p in value.split('/')) and '\\' not in value
    return value


def bindings(contract, inventory):
    assert len(inventory) == 543 and contract['SdkVersion'] == '10.0.400'
    nodes = {row['key']: row for row in inventory}
    assert len(nodes) == len(inventory)
    managed = {key: row for key, row in nodes.items()
               if row['values']['TargetPath'] and row['values']['IsCrossTargetingBuild'] != 'true'}
    assert len(managed) == 481
    products = {relative(row['values']['TargetPath']): key for key, row in managed.items()}
    assert len(products) == len(managed)
    declared_inputs = set(contract['SharedInputs']) | {path for project in contract['Projects'].values()
        for variant in [project] + project.get('Configurations', []) for path in variant['Inputs']}
    closures = {}

    def closure(key):
        if key not in closures:
            pending = list(nodes[key]['dependencies'])
            found = set()
            while pending:
                child = pending.pop()
                if child not in found:
                    found.add(child)
                    pending.extend(nodes[child]['dependencies'])
            closures[key] = found
        return closures[key]

    selected = {}
    for key, row in managed.items():
        target = row['values']['TargetPath']
        annotated = {item['referenceAssembly'] for items in row['targets'].values() for item in items
                     if item['path'] == target and item['referenceAssembly']}
        if not annotated and row['values']['AnnotateTargetPathWithContract'] == 'true':
            annotated = {item['path'] for item in row['items']['ResolvedMatchingContract']}
        assert len(annotated) <= 1, ('Ambiguous advertised contract', key, annotated)
        artifact = relative(next(iter(annotated), target))
        assert artifact in products and products[artifact] in closure(key) | {key}, ('Unowned contract', key, artifact)
        selected[key] = artifact

    reviewed = defaultdict(list)
    compiler_inputs = 0
    for key, row in managed.items():
        project = row['project']
        variants = contract['Projects'][project].get('Configurations') or [contract['Projects'][project]]
        variant = next(v for v in variants if all(row['properties'].get(p, '') == value for p, value in v.get('Properties', {}).items()))
        dependency_keys = closure(key)
        actual = defaultdict(set)
        for item in row['items']['ReferencePathWithRefAssemblies']:
            if item['path'].startswith(PREFIX):
                path = relative(item['path'])
                if path in products:
                    assert products[path] in dependency_keys, ('Compiler product outside dependencies', key, path)
                    actual[PurePosixPath(path).name].add(path)
                else:
                    assert path in declared_inputs or path.startswith('.nuget/'), ('Unaccounted compiler input', key, path)
            else:
                assert item['path'].startswith('/__rules_msbuild_graph/sdk/'), ('External compiler input', key, item['path'])
        overrides = dict(variant.get('CompilerReferences', {}))
        for producer in dependency_keys & managed.keys():
            output = relative(managed[producer]['values']['TargetPath'])
            choices = actual[PurePosixPath(output).name]
            if not choices:
                continue
            assert len(choices) == 1, ('Ambiguous compiler input', key, choices)
            path = next(iter(choices))
            if any(products[path] in closure(other) | {other} for other in dependency_keys & managed.keys()
                   if managed[other]['project'] == managed[producer]['project']):
                producer_path = managed[producer]['project']
                assert producer_path not in overrides or overrides[producer_path] == path, ('Conflicting consumer selection', key, producer_path)
                overrides[producer_path] = path
        actual_paths = {path for paths in actual.values() for path in paths}
        assert actual_paths <= set(overrides.values()), ('Unbound SDK compiler inputs', key, actual_paths - set(overrides.values()))
        compiler_inputs += len(actual_paths)
        implementations = set(variant.get('ImplementationDependencies', []))
        implementations.update(item['path'] for item in row['authoredReferences'] if item['skipReferenceAssembly'].lower() == 'true')
        assert implementations <= {nodes[child]['project'] for child in row['dependencies']}
        copies = dict(variant.get('DependencyCopies', {}))
        destinations = {str(PurePosixPath(relative(row['values']['TargetPath'])).parent)}
        publish = row['values']['PublishDir']
        if publish:
            if not publish.startswith('/'):
                publish = PREFIX + str(PurePosixPath(project).parent / publish)
            destinations.add(relative(publish.rstrip('/')))
        for item in row['items']['ReferenceCopyLocalPaths']:
            if not item['path'].startswith(PREFIX):
                continue
            path = relative(item['path'])
            producer = str(PurePosixPath(path).with_suffix('.dll'))
            if producer not in products or products[producer] not in dependency_keys:
                continue
            # Absent PDB/XML siblings remain optional. The cache verifies every
            # actual copy against the selected producer before storing a snapshot.
            for extension in ['.dll', '.pdb', '.xml']:
                source = str(PurePosixPath(producer).with_suffix(extension))
                for directory in destinations:
                    copies[directory + '/' + PurePosixPath(source).name] = source
        reviewed[project].append(dict(properties=variant.get('Properties', {}), framework=row['values']['TargetFramework'],
                                      bindings=dict(referenceBoundary=True, compilerReference=selected[key],
                                                    compilerReferences=overrides, implementationDependencies=sorted(implementations), dependencyCopies=copies)))
    advertised_contracts = sum(selected[key] != relative(row['values']['TargetPath']) for key, row in managed.items())
    assert advertised_contracts == 233
    return dict(sdkVersion=contract['SdkVersion'], configuredNodes=len(nodes), compiledNodes=len(managed),
                compilerInputs=compiler_inputs, advertisedContracts=advertised_contracts,
                projects=dict(sorted(reviewed.items())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('contract', type=Path)
    parser.add_argument('inventory', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = bindings(json.loads(args.contract.read_text()), json.loads(args.inventory.read_text()))
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print('Bound all', result['compiledNodes'], 'managed configurations; SDK choices retained')


if __name__ == '__main__':
    main()
