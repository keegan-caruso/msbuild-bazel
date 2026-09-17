import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from native_graph import qualify, relative

class NativeGraph(unittest.TestCase):
    def graph(self):
        return dict(entryPoints=['n'],nodes=[dict(id='n',project='workspace/src/Library/Library.csproj',globalProperties={'configuration':'Release','targetframework':'net10.0'},targetFramework='net10.0',outputType='Library',dependencies=[],outputs=[dict(kind='assembly',path='workspace/src/Library/bin/Release/net10.0/Library.dll')],execution=dict(outputDirectory='workspace/src/Library/bin/Release/net10.0',referenceDirectory='workspace/src/Library/obj/Release/net10.0/ref'))])
    def test_nested_evaluated_project(self):self.assertEqual(len(qualify(self.graph())),1)
    def test_configuration_and_layout_reject(self):
        for field,value in (('globalProperties',{'configuration':'Debug','targetframework':'net10.0'}),('outputs',[]),('dependencies',['missing'])):
            g=self.graph();g['nodes'][0][field]=value
            with self.assertRaises(ValueError):qualify(g)
    def test_path_escape_reject(self):
        for p in ('packages/file','workspace/../outside','workspace//absolute'):
            with self.assertRaises(ValueError):relative(p)
