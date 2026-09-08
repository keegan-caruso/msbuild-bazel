import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from graph_packages import package_plan


class SelectedPackagesTests(unittest.TestCase):
    def test_unselected_framework_cannot_override_privacy_or_asset_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'obj').mkdir()
            (root / 'Example.csproj').write_text('''<Project><ItemGroup>
<PackageReference Include="Example" Version="[1.0.0]" PrivateAssets="all" />
<PackageReference Update="Example" PrivateAssets="none" Condition="'$(TargetFramework)' == 'netstandard2.0'" />
</ItemGroup></Project>''')
            net10 = dict(dependencies={'Example': dict(suppressParent='All')})
            netstandard = dict(dependencies={'Example': dict(suppressParent='None')})
            for frameworks in ({'net10.0': net10, 'netstandard2.0': netstandard},
                               {'netstandard2.0': netstandard, 'net10.0': net10}):
                assets = dict(project=dict(frameworks=frameworks), libraries={
                    'Example/1.0.0': dict(type='package', path='example/1.0.0', sha512='hash'),
                    'Unselected/1.0.0': dict(type='package', path='unselected/1.0.0', sha512='hash')},
                    targets={'net10.0': {'Example/1.0.0': {}},
                             'netstandard2.0': {'Example/1.0.0': {'native': {'bad': {}}}, 'Unselected/1.0.0': {}}})
                (root / 'obj/project.assets.json').write_text(json.dumps(assets))
                _, libraries = package_plan(root, 'Example.csproj', target_framework='net10.0')
                self.assertEqual({'Example/1.0.0'}, set(libraries))
                with self.assertRaisesRegex(ValueError, 'explicit selected'):
                    package_plan(root, 'Example.csproj')
                with self.assertRaisesRegex(ValueError, 'selected package target missing'):
                    package_plan(root, 'Example.csproj', target_framework='net11.0')
