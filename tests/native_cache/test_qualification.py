import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from probe_native_cache import qualify, input_hash
from synthetic_graph import generate

class Qualification(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'fixture';generate(self.root,10,'fan')

    def test_authored_paths_remain_exact(self):
        self.assertNotEqual(input_hash("N/A.cs", b'/one', Path("/one")),
                            input_hash("N/A.cs", b'/two', Path("/two")))

    def test_restore_paths_are_relocatable(self):
        self.assertEqual(input_hash("N/obj/project.assets.json", b'/one/N', Path("/one")),
                         input_hash("N/obj/project.assets.json", b'/two/N', Path("/two")))

    def test_ordinary_fixture(self):
        self.assertEqual(len(qualify(self.root)),10)

    def test_required_switch_cannot_disappear(self):
        p=self.root/'Directory.Build.props';p.write_text(p.read_text().replace('<DisableTransitiveProjectReferences>true</DisableTransitiveProjectReferences>',''))
        with self.assertRaises(ValueError):qualify(self.root)

    def test_custom_task_and_content_reject(self):
        p=self.root/'N0000/N0000.csproj';original=p.read_text()
        for xml in ('<Target Name="Hidden"/>','<ItemGroup><Content Include="data"/></ItemGroup>'):
            p.write_text(original.replace('</Project>',xml+'</Project>'))
            with self.assertRaises(ValueError):qualify(self.root)

    def test_external_reference_reject(self):
        p=self.root/'N0001/N0001.csproj';p.write_text(p.read_text().replace('../N0000/N0000.csproj','../../elsewhere.csproj'))
        with self.assertRaises(ValueError):qualify(self.root)

    def test_restore_import_reject(self):
        p=self.root/'N0000/obj/N0000.csproj.nuget.g.targets';p.parent.mkdir()
        p.write_text('<Project><Import Project="external.targets"/></Project>')
        with self.assertRaises(ValueError):qualify(self.root)

    def test_package_payload_reject(self):
        p=self.root/'N0000/obj/project.assets.json';p.parent.mkdir();p.write_text(json.dumps({'libraries':{'p/1':{'type':'package'}}}))
        with self.assertRaises(ValueError):qualify(self.root)

    def test_symlink_reject(self):
        (self.root/'N0000/link.cs').symlink_to('Value.cs')
        with self.assertRaises(ValueError):qualify(self.root)

    def test_nested_props_reject(self):
        (self.root/'N0000/Directory.Build.props').write_text('<Project><Target Name="Hidden"/></Project>')
        with self.assertRaises(ValueError):qualify(self.root)

    def test_sdk_selection_reject(self):
        (self.root/'global.json').write_text('{"sdk":{"version":"10.0.400","rollForward":"latestMajor"}}')
        with self.assertRaises(ValueError):qualify(self.root)

    def test_unexpected_namespace_input_reject(self):
        (self.root/'Directory.Build.targets').write_text('<Project/>')
        with self.assertRaises(ValueError):qualify(self.root)

if __name__=='__main__':unittest.main()
