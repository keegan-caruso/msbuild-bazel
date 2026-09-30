"""Expand reviewed contracts for the pinned macOS ARM64 System.IO.Pipelines slice.

The output list records BinPlace producers, not a runtime filesystem scan.
Do not reuse it for another platform, framework, target or upstream revision.
"""

import argparse
import copy
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    mapping = json.loads((directory / 'runtime.json').read_text())
    mapping['projects'] = {}
    for project, frameworks in json.loads((directory / 'runtime_outputs.json').read_text()).items():
        binding = copy.deepcopy(mapping['projectDefaults'])
        binding.pop('properties')
        for framework, outputs in frameworks.items():
            if framework:
                configured = copy.deepcopy(binding)
                configured['outputFiles'] += outputs
                binding.setdefault('frameworkOverrides', {})[framework] = configured
            else:
                binding['outputFiles'] += outputs
        mapping['projects'][project] = binding
    args.output.write_text(json.dumps(mapping, indent=2) + '\n')


if __name__ == '__main__':
    main()
