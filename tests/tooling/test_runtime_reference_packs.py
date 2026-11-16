"""Reference packs follow the selected SDK and the verified NuGet lock."""
import json
import os
from unittest.mock import patch
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tests/graph_build/upstream'))
from runtime_product_declarations import reference_packs, declare_product
from runtime_prepare import COMMIT


class ReferencePackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sdk = self.root/'sdk-root'
        directory = self.sdk/'sdk/11.0.100'
        directory.mkdir(parents=True)
        self.props = directory/'Microsoft.NETCoreSdk.BundledVersions.props'
        self.props.write_text('''<Project><ItemGroup>
<KnownFrameworkReference Include="Microsoft.NETCore.App" TargetFramework="net10.0" TargetingPackName="Microsoft.NETCore.App.Ref" TargetingPackVersion="10.0.15" />
<KnownFrameworkReference Include="Microsoft.AspNetCore.App" TargetFramework="net10.0" TargetingPackName="Microsoft.AspNetCore.App.Ref" TargetingPackVersion="10.0.15" />
<KnownFrameworkReference Include="Microsoft.NETCore.App" TargetFramework="net9.0" TargetingPackName="Microsoft.NETCore.App.Ref" TargetingPackVersion="9.0.23" />
</ItemGroup></Project>''')
        self.packages = [dict(id='Microsoft.NETCore.App.Ref', version='10.0.15', sha256='a'*64),
            dict(id='Microsoft.AspNetCore.App.Ref', version='10.0.15', sha256='b'*64),
            dict(id='Microsoft.NETCore.App.Ref', version='9.0.23', sha256='c'*64)]
        self.save()

    def save(self, version='11.0.100'):
        (self.root/'nuget.lock.json').write_text(json.dumps(dict(sdkVersion=version, packages=self.packages)))

    def test_selected_packs_and_sdk10_no_dependency(self):
        self.save('10.0.400')
        self.assertEqual(reference_packs(self.root, '10.0.400', self.sdk), ([], []))
        self.save()
        labels, digests = reference_packs(self.root, '11.0.100', self.sdk)
        self.assertEqual(labels, ['@nuget//:microsoft.netcore.app.ref__10.0.15',
                                  '@nuget//:microsoft.aspnetcore.app.ref__10.0.15'])
        self.assertEqual(digests, ['a'*64, 'b'*64])

    def test_product_declaration_binds_narrow_lock_and_digest_contract(self):
        workspace = self.root/'workspace'; workspace.mkdir()
        native = self.root/'native'; native.mkdir()
        for name in ('native', 'libraries', 'host'):
            folder = native/name; folder.mkdir()
            data = dict(commit=COMMIT, jobs=4, generator='Ninja', products={},
                        inputs={'toolchain.tar': {'sha256': 'd'*64}})
            (folder/'acquisition.json').write_text(json.dumps(data))
        (native/'libraries/products.json').write_text('{"products": {}}')
        (workspace/'native').mkdir(); (workspace/'native/BUILD.bazel').write_text('')
        for name, contents in (('BUILD.bazel', ''), ('MODULE.bazel', ''),
                               ('graph.generated.json', json.dumps({'SdkVersion':'11.0.100'}))):
            (workspace/name).write_text(contents)
        (workspace/'nuget.lock.json').write_text((self.root/'nuget.lock.json').read_text())
        with patch.dict(os.environ, {'RULES_MSBUILD_DOTNET_ROOT': str(self.sdk)}), \
             patch('runtime_product_declarations.declare_native'):
            declare_product(workspace, native, {'producers': {}})
        contract = json.loads((workspace/'app/contract.json').read_text())
        self.assertEqual(contract['SdkVersion'], '11.0.100')
        self.assertEqual(contract['PackageDigests'], ['a'*64, 'b'*64])
        build = (workspace/'BUILD.bazel').read_text()
        self.assertIn('@nuget//:microsoft.netcore.app.ref__10.0.15', build)
        self.assertIn('@nuget//:microsoft.aspnetcore.app.ref__10.0.15', build)
        self.assertNotIn('9.0.23', build)
        macro = (workspace/'runtime_product.bzl').read_text()
        self.assertIn('msbuild_package_lock(', macro)
        self.assertIn('package_lock', macro)

    def test_wrong_sdk_missing_duplicate_and_conditional_selection_fail(self):
        self.save('11.0.101')
        with self.assertRaisesRegex(ValueError, 'SDK version differs'):
            reference_packs(self.root, '11.0.100', self.sdk)
        self.packages.pop(1); self.save()
        with self.assertRaisesRegex(ValueError, 'Missing or ambiguous'):
            reference_packs(self.root, '11.0.100', self.sdk)
        self.packages.append(self.packages[0]); self.save()
        with self.assertRaisesRegex(ValueError, 'Missing or ambiguous'):
            reference_packs(self.root, '11.0.100', self.sdk)
        self.props.write_text(self.props.read_text().replace('TargetFramework="net10.0"', 'Condition="x" TargetFramework="net10.0"', 1))
        with self.assertRaisesRegex(ValueError, 'unconditional'):
            reference_packs(self.root, '11.0.100', self.sdk)


if __name__ == '__main__':
    unittest.main()
