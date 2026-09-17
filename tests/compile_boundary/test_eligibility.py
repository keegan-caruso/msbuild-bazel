import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from compile_boundary import validate

class Eligibility(unittest.TestCase):
    def test_custom_implementation_inputs_reject(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            node=dict(globalProperties={'configuration':'Release'},id='one',dependencies=[],project='workspace/App.csproj',targetFramework='net10.0',outputType='Library',execution={'assetsFile':'workspace/obj/project.assets.json'})
            for body in ('<Target Name="Build"/>','<UsingTask TaskName="T" AssemblyFile="X.dll"/>',
                         '<ItemGroup><ProjectReference Include="Gen.csproj" OutputItemType="Analyzer"/></ItemGroup>',
                         '<ItemGroup><Reference Include="X"/></ItemGroup>',
                         '<ItemGroup><Content Include="data"/></ItemGroup>'):
                (root/'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk">'+body+'</Project>')
                node['inputs']=[dict(kind='project',path='workspace/App.csproj')]
                with patch('compile_boundary.package_plan',return_value=({},{})), self.subTest(body=body), self.assertRaises(ValueError):
                    validate(root,{'nodes':[node]})
            for item in (dict(kind='analyzer',path='workspace/gen.dll'),dict(kind='package',path='packages/pkg.dll')):
                node['inputs']=[item]
                with patch('compile_boundary.package_plan',return_value=({},{})), self.assertRaises(ValueError):
                    validate(root,{'nodes':[node]})

if __name__=='__main__':unittest.main()
