"""Expand reviewed contracts for pinned ARM64 System.IO.Pipelines slices.

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
    parser.add_argument('--platform', choices=['osx-arm64', 'linux-arm64'], default='osx-arm64')
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    mapping = json.loads((directory / 'runtime.json').read_text())
    if args.platform == 'linux-arm64':
        mapping['projectDefaults']['properties']['TargetOS'] = 'linux'
        # Reviewed host/mobile coordination and runner-command items are
        # metadata, not file inputs consumed by this Linux managed Build.
        mapping['projectDefaults']['evaluationItems'] += [
            'ManagedProjectToBuild', 'MonoAotCrossCompiler', 'SetScriptCommands']
        mapping['projectDefaults']['documents'].update(json.loads((directory / 'runtime_test_documents.json').read_text()))
    mapping['projects'] = {}
    output_file = 'runtime_linux_outputs.json' if args.platform == 'linux-arm64' else 'runtime_outputs.json'
    for project, frameworks in json.loads((directory / output_file).read_text()).items():
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
