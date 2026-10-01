"""Expand reviewed contracts for pinned ARM64 runtime managed slices.

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
        mapping['projectDefaults']['inputItems']['RdXmlFile'] = []
        # API validation discovers this authored suppression file in a target.
        project = 'src/libraries/System.Runtime.InteropServices/src/System.Runtime.InteropServices.csproj'
        mapping['projectDefaults']['documents'][project] = {
            'sha256': 'd2211022a663a767f971105013f896ded556304d441e970bdaaeb70ebeed1061',
            'targets': [], 'tasks': [],
            'inputs': ['src/libraries/System.Runtime.InteropServices/src/CompatibilitySuppressions.xml']}
    # The linker embeds this property-selected file inside _EmbedILLinkXmls.
    project = 'src/libraries/System.Linq/src/System.Linq.csproj'
    mapping['projectDefaults']['documents'][project] = {
        'sha256': '88c4fbf7cfb16c9ecdd59bdeec0255390493b075d78bced3559bc23c24eef8a5',
        'targets': [], 'tasks': [],
        'inputs': ['src/libraries/System.Linq/src/ILLink/ILLink.Descriptors.xml']}
    # DiagnosticSource generates version metadata from an authored template.
    project = 'src/libraries/System.Diagnostics.DiagnosticSource/src/System.Diagnostics.DiagnosticSource.csproj'
    mapping['projectDefaults']['documents'][project] = {
        'sha256': '97d33339566e0a80f833fd58f5f7010d2d3a1a1afeeff4fb4f1d014ca5265ac1',
        'targets': ['_GenerateThisAssemblyInfo'], 'tasks': [],
        'inputs': ['src/libraries/System.Diagnostics.DiagnosticSource/src/ThisAssembly.cs.in']}
    # The XLIFF package discovers these translations inside a target, so they
    # are not evaluated file items. Bind them to the projects owning the resx.
    generator_root = 'src/libraries/System.Runtime.InteropServices/gen/'
    translations = [generator_root + f'Common/Resources/xlf/Strings.{language}.xlf'
                    for language in ['cs', 'de', 'es', 'fr', 'it', 'ja', 'ko',
                                     'pl', 'pt-BR', 'ru', 'tr', 'zh-Hans', 'zh-Hant']]
    generator_documents = {
        'ComInterfaceGenerator': '34459bd522f5178b97059a2847099199b0ebed15b059ddac90c480f09e01026f',
        'LibraryImportGenerator': '48b5cec5bb4db0fb9e9bb2cc7e6c5390f9767e75e2c188d1cd6e24f548e8258a',
        'DownlevelLibraryImportGenerator': 'd10e1444668f7e19a9b2f4cb5c2f01585d9548b562b44453d31a0a9619130962',
        'Microsoft.Interop.SourceGeneration': '469e452d8e496806630e140b1769a8e3d433b4f1d0ee3cfd90892f92a709457e',
    }
    for name, digest in generator_documents.items():
        mapping['projectDefaults']['documents'][generator_root + f'{name}/{name}.csproj'] = {
            'sha256': digest, 'targets': [], 'tasks': [], 'inputs': translations}
    json_root = 'src/libraries/System.Text.Json/gen/'
    translations = [json_root + f'Resources/xlf/Strings.{language}.xlf'
                    for language in ['cs', 'de', 'es', 'fr', 'it', 'ja', 'ko',
                                     'pl', 'pt-BR', 'ru', 'tr', 'zh-Hans', 'zh-Hant']]
    for version, digest in {
        '3.11': '87631a718a7e46cc2123befe01384f90193c4d4157d182646c4925cfd5129528',
        '4.0': 'a82133743ef0db8beae1ad4cd39635176a76d4df9de22ffd239709cd91a90656',
        '4.4': '518aae0fa687ec52580b0058abac7486ed0efc1bca35ce2b700dfb9f7574dac2',
    }.items():
        mapping['projectDefaults']['documents'][json_root + f'System.Text.Json.SourceGeneration.Roslyn{version}.csproj'] = {
            'sha256': digest, 'targets': [], 'tasks': [], 'inputs': translations}
    # ASN transforms compare generated C# with checked-in source. Changes to
    # authored source remain subject to the runner's input-mutation guard.
    project = 'src/libraries/Common/src/System/Security/Cryptography/Asn1/AsnXml.targets'
    mapping['projectDefaults']['documents'][project] = {
        'sha256': '4bb2ccaa6166a28428b8de6e743bb1a3318d5a0a92e24d79ca501d09feac754a',
        'targets': ['CompileAsn'], 'tasks': ['CompareFilesIgnoreLineEndings'],
        'inputs': ['src/libraries/Common/src/System/Security/Cryptography/Asn1/asn.xslt']}
    mapping['projectDefaults']['inputItems']['AsnXml'] = []
    mapping['projectDefaults']['evaluationItems'].append('DefaultReferenceExclusion')
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
    # ASN targets write comparison scratch and may skip individual transforms
    # after another framework touches the common checked-in C# output. These
    # intermediate files are not compiler inputs or downstream products.
    for project in ['src/libraries/System.Security.Cryptography/src/System.Security.Cryptography.csproj',
                    'src/libraries/System.Formats.Asn1/src/System.Formats.Asn1.csproj']:
        binding = mapping['projects'].setdefault(project, copy.deepcopy(mapping['projectDefaults']))
        binding.pop('properties', None)
        for variant in [binding] + list(binding.get('frameworkOverrides', {}).values()):
            variant['temporaryDirectories'] = ['$(IntermediateOutputPath)asnxml']
    if args.platform == 'linux-arm64':
        # This library consumes SDK compiler references. Retain implementation
        # dependencies for the source-generator projects built alongside it.
        project = 'src/libraries/System.Text.Json/src/System.Text.Json.csproj'
        binding = mapping['projects'].setdefault(project, copy.deepcopy(mapping['projectDefaults']))
        binding.pop('properties', None)
        generators = ['src/libraries/System.Text.Json/gen/System.Text.Json.SourceGeneration.Roslyn' + version + '.csproj'
                      for version in ['3.11', '4.0', '4.4']]
        for variant in [binding] + list(binding.get('frameworkOverrides', {}).values()):
            variant['referenceBoundary'] = True
            variant['implementationDependencies'] = generators
        configured = copy.deepcopy(binding.get('frameworkOverrides', {}).get('net10.0', binding))
        configured.pop('frameworkOverrides', None)
        # The SDK builds all Pipelines variants for coordination, but net10
        # Json consumes this single authored compiler contract. Retain both
        # implementation and ref project identities without hashing other DLLs.
        pipeline = 'src/libraries/System.IO.Pipelines/'
        artifact = 'artifacts/bin/System.IO.Pipelines/ref/$(Configuration)/net10.0/System.IO.Pipelines.dll'
        configured['compilerReferences'] = {
            pipeline + 'src/System.IO.Pipelines.csproj': artifact,
            pipeline + 'ref/System.IO.Pipelines.csproj': artifact,
        }
        binding.setdefault('frameworkOverrides', {})['net10.0'] = configured
        # This SDK workaround lists RID platform names, not paths. Its PNS
        # configuration discovers a separate authored exclusion file in a target.
        project = 'src/libraries/System.Net.Quic/src/System.Net.Quic.csproj'
        binding = mapping['projects'].setdefault(project, copy.deepcopy(mapping['projectDefaults']))
        binding.pop('properties', None)
        for variant in [binding] + list(binding.get('frameworkOverrides', {}).values()):
            variant['evaluationItems'].append('_KnownRuntimeIdentiferPlatforms')
            variant['documents'][project] = {
                'sha256': '7f388295fe9b0043f8359ba6f8048c78df4c518849cf28ba5506958019c66f4d',
                'targets': [], 'tasks': [],
                'inputs': ['src/libraries/System.Net.Quic/src/ExcludeApiList.PNSE.txt']}
    if args.platform == 'linux-arm64':
        # These authored files are discovered inside SDK/upstream targets rather
        # than evaluated file items. Retain the upstream validation/generation.
        for project, digest, extra in [
            ('src/libraries/System.Net.Security/src/System.Net.Security.csproj',
             '98ebdd8a237a7a622a7673cfd81e2e83720aab5bb7a9ec7080c38774fe520867',
             'src/libraries/System.Net.Security/src/ExcludeApiList.PNSE.txt'),
            ('src/libraries/System.Collections.Specialized/src/System.Collections.Specialized.csproj',
             'cc51f6d28ce66b7ad9a6ceef8ab6bbd5176c71af179f0570ac6f40e921df017f',
             'src/libraries/System.Collections.Specialized/src/CompatibilitySuppressions.xml'),
        ]:
            binding = mapping['projects'].setdefault(project, copy.deepcopy(mapping['projectDefaults']))
            binding.pop('properties', None)
            for variant in [binding] + list(binding.get('frameworkOverrides', {}).values()):
                variant['documents'][project] = {'sha256': digest, 'targets': [], 'tasks': [], 'inputs': [extra]}
    if args.platform == 'linux-arm64':
        # Only the browser configuration reads this PNS generation exclusion.
        project = 'src/libraries/System.Net.NameResolution/src/System.Net.NameResolution.csproj'
        binding = mapping['projects'].setdefault(project, copy.deepcopy(mapping['projectDefaults']))
        binding.pop('properties', None)
        configured = copy.deepcopy(binding.get('frameworkOverrides', {}).get('net10.0-browser', binding))
        configured.pop('frameworkOverrides', None)
        configured['documents'][project] = {
            'sha256': 'd37182c9f228d8176df5d88719692195596e6cead3002d2e5e7a2c7044d51bc0',
            'targets': [], 'tasks': [],
            'inputs': ['src/libraries/System.Net.NameResolution/src/ExcludeApiList.PNSE.Browser.txt']}
        binding.setdefault('frameworkOverrides', {})['net10.0-browser'] = configured
    if args.platform == 'linux-arm64':
        # Shim stubs generate C# from authored type names before CoreCompile.
        # These are metadata, not file paths; preserve the SDK-generated output.
        document = 'src/libraries/shims/stubs/Directory.Build.targets'
        reviewed = {
            'sha256': '33bd774981a6196c9622fa042ec89c43ca7da97bc60e972687d346c6c86d42aa',
            'targets': ['CreateCompileSourceForForwardedTypes'], 'tasks': [], 'inputs': []}
        for name in ['Microsoft.Win32.SystemEvents', 'System.CodeDom',
                     'System.Configuration.ConfigurationManager', 'System.Data.Odbc',
                     'System.Data.OleDb', 'System.Data.SqlClient', 'System.Diagnostics.EventLog',
                     'System.Diagnostics.PerformanceCounter', 'System.Drawing.Common',
                     'System.IO.Packaging', 'System.IO.Ports', 'System.Runtime.Serialization.Schema',
                     'System.Security.Cryptography.Pkcs', 'System.Security.Cryptography.ProtectedData',
                     'System.Security.Cryptography.Xml', 'System.Security.Permissions',
                     'System.ServiceModel.Syndication', 'System.ServiceProcess.ServiceController',
                     'System.Windows.Extensions']:
            project = 'src/libraries/shims/stubs/' + name + '.csproj'
            binding = mapping['projects'].setdefault(project, copy.deepcopy(mapping['projectDefaults']))
            binding.pop('properties', None)
            for variant in [binding] + list(binding.get('frameworkOverrides', {}).values()):
                variant['documents'][document] = reviewed
                variant['evaluationItems'].append('ForwardedType')
        # The pinned generator declares an empty IDE folder. It has no files
        # or target consumer; do not turn it into recursive input discovery.
        project = 'src/libraries/System.Runtime.InteropServices.JavaScript/gen/JSImportGenerator/JSImportGenerator.csproj'
        binding = mapping['projects'].setdefault(project, copy.deepcopy(mapping['projectDefaults']))
        binding.pop('properties', None)
        for variant in [binding] + list(binding.get('frameworkOverrides', {}).values()):
            variant['evaluationItems'].append('Folder')
            variant['documents'][project] = {
                'sha256': 'ba17878f95c3c8059ec58ad2b8fbd84e0e34e4af3fedccd1df49211fc0353d3c',
                'targets': [], 'tasks': [], 'inputs': []}
    args.output.write_text(json.dumps(mapping, indent=2) + '\n')


if __name__ == '__main__':
    main()
