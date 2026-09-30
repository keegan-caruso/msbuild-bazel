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
    parser.add_argument('--prepared-restore', action='store_true', help='declare the reviewed managed graph Restore contract')
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
    # The XLIFF package discovers these translations inside a target, so they
    # are not evaluated file items. Bind them to the projects owning the resx.
    generator_root = 'src/libraries/System.Runtime.InteropServices/gen/'
    translations = [generator_root + f'Common/Resources/xlf/Strings.{language}.xlf'
                    for language in ['cs', 'de', 'es', 'fr', 'it', 'ja', 'ko',
                                     'pl', 'pt-BR', 'ru', 'tr', 'zh-Hans', 'zh-Hant']]
    generator_documents = {
        'LibraryImportGenerator': '48b5cec5bb4db0fb9e9bb2cc7e6c5390f9767e75e2c188d1cd6e24f548e8258a',
        'DownlevelLibraryImportGenerator': 'd10e1444668f7e19a9b2f4cb5c2f01585d9548b562b44453d31a0a9619130962',
        'Microsoft.Interop.SourceGeneration': '469e452d8e496806630e140b1769a8e3d433b4f1d0ee3cfd90892f92a709457e',
    }
    for name, digest in generator_documents.items():
        mapping['projectDefaults']['documents'][generator_root + f'{name}/{name}.csproj'] = {
            'sha256': digest, 'targets': [], 'tasks': [], 'inputs': translations}
    if args.prepared_restore:
        mapping['projectDefaults']['preparedRestore'] = True
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
