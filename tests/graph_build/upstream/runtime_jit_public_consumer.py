"""Close generated JIT modules over authored inputs and declared producer artifacts.

Relocate to another machine with a fresh output base and stop the producer before
runtime_jit_public.py --seed-report. No outputs or local caches are copied.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prepared', type=Path, help='runtime_jit_public_prepare.py output')
    parser.add_argument('seed_report', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    source, output = args.prepared.resolve(), args.output.resolve()
    assert not output.exists() and not output.is_relative_to(source)
    seed = json.loads(args.seed_report.read_text())
    products = source / 'workspace/source-products.tar.gz'
    assert hashlib.sha256(products.read_bytes()).hexdigest() == seed['sourceProductsSha256']
    output.mkdir(parents=True)
    counts = {}
    for name in ['bootstrap', 'workspace']:
        root, target = source / name, output / name
        contract = json.loads((root / 'graph.generated.json').read_text())
        wanted = {'BUILD.bazel', 'MODULE.bazel', 'graph.generated.bzl', 'graph.generated.json', 'mappings.json', 'nuget.lock.json'}
        if name == 'workspace':
            wanted.update(['jit-public.json', 'products.bzl', 'source-products.tar.gz'])
        wanted.update(contract['SharedInputs'])
        wanted.update(contract.get('DefinitionDigests', {}))
        wanted.update(contract.get('Restore', {}).get('Inputs', []))
        for project in contract['Projects'].values():
            wanted.update(project['Inputs'])
            for config in project.get('Configurations', []):
                wanted.update(config['Inputs'])
        trees = tuple(root + '/' for root in contract.get('InputTrees', {}))
        wanted = {path for path in wanted if not path.startswith(trees + ('.nuget/', '.graph-tools/'))}
        for path in sorted(wanted):
            relative = Path(path)
            assert not relative.is_absolute() and '..' not in relative.parts
            original = root / relative
            assert original.is_file() and original.resolve().is_relative_to(root), path
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, destination)
        module = (target / 'MODULE.bazel').read_text()
        module = re.sub(r'local_path_override\(module_name="rules_msbuild",path="[^"]+"\)',
            'local_path_override(module_name="rules_msbuild",path=' + json.dumps(str(ROOT)) + ')', module)
        module = re.sub(r'local_path_override\(module_name="jit_bootstrap",path="[^"]+"\)',
            'local_path_override(module_name="jit_bootstrap",path="../bootstrap")', module)
        (target / 'MODULE.bazel').write_text(module)
        counts[name] = len(wanted)
    for path, digest in seed['sourceDigests'].items():
        assert hashlib.sha256((output / 'workspace' / path).read_bytes()).hexdigest() == digest, path
    shutil.copyfile(args.seed_report, output / 'seed.json')
    (output / 'consumer.json').write_text(json.dumps(dict(copiedInputs=counts,
        sourceProductsSha256=seed['sourceProductsSha256'], scope='generated public modules; no outputs or local cache'), indent=2) + '\n')
    print(output, flush=True)


if __name__ == '__main__':
    main()
