"""Restore normalization must be portable and reject failed restore receipts."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


class RestoreInputs(unittest.TestCase):
    def test_relocated_metadata_has_identical_normalized_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);outputs=[]
            for name in ['first','relocated']:
                source=root/name;source.mkdir();cache=root/(name+'-packages')
                assets=source/'assets';receipt=source/'receipt'
                assets.write_text(json.dumps(dict(project=str(source/'App.csproj'),packageFolders={str(cache)+'/':{}},other=str(source)+'-other/file')))
                receipt.write_text(json.dumps(dict(success=True,dgSpecHash=name,projectFilePath=str(source/'App.csproj'))))
                out=root/(name+'-output');request=root/'request.json'
                request.write_text(json.dumps(dict(workspace=str(source),cache=str(cache),files=[dict(source=str(assets),output=str(out/'assets'),name='App/obj/project.assets.json'),dict(source=str(receipt),output=str(out/'receipt'),name='App/obj/project.nuget.cache')])))
                result=subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'),str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'),'owned-normalize-restore','--request',str(request)],capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr)
                value=json.loads((out/'assets').read_text());self.assertEqual(value.pop('other'),str(source)+'-other/file')
                self.assertEqual(value['project'],'${WORKSPACE}/App.csproj')
                self.assertEqual(value['packageFolders'],{'${WORKSPACE}/.nuget/packages/':{}})
                outputs.append((value,(out/'receipt').read_bytes()))
            self.assertEqual(outputs[0],outputs[1])
            receipt.write_text('{"success":false}')
            result=subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'),str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'),'owned-normalize-restore','--request',str(request)],capture_output=True,text=True,timeout=30)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Unsuccessful restore',result.stderr)
