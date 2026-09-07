"""Bounded Nix import declarations; no SDK compilation required."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_graph import nix_imports

IMPORTS = ['/nix/store/7j5z3nhm7kqc12lw46153fbahbbdxf7k-extra.targets',
           '/nix/store/ik0wdskh7nw2l9kj31g57k2zkc31i06v-sign-apphost.proj']
SDK = os.environ.get('SPIKE_DOTNET_ROOT', '')


class NixImportDeclarations(unittest.TestCase):
    def test_imports_are_sorted_deduplicated_and_explicit(self):
        items = [dict(kind='import', path='nix/' + Path(path).name) for path in reversed(IMPORTS)]
        self.assertEqual(nix_imports(items + items, '/nix/store/' + '0'*32 + '-sdk'), IMPORTS)
        self.assertEqual(nix_imports([dict(kind='source', path='workspace/App.cs')], '/local/sdk'), [])

    def test_other_input_kinds_cannot_use_nix_root(self):
        for kind in ('source', 'package', 'extra', 'restore'):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'unsupported Nix SDK import'):
                nix_imports([dict(kind=kind,path='nix/'+Path(IMPORTS[0]).name)], '/nix/store/sdk')

    def test_nonnix_sdk_and_unsafe_names_reject(self):
        with self.assertRaisesRegex(ValueError, 'unsupported Nix SDK import'):
            nix_imports([dict(kind='import',path='nix/'+Path(IMPORTS[0]).name)], '/local/sdk')
        for value in ('nix/', 'nix/not-store-name', 'nix/'+Path(IMPORTS[0]).name+'/../escape', 'nix/'+Path(IMPORTS[0]).name+'/./file', 'nix/'+Path(IMPORTS[0]).name+'//file'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'unsupported Nix SDK import'):
                nix_imports([dict(kind='import',path=value)], '/nix/store/sdk')

    @unittest.skipUnless(SDK.startswith('/nix/store/') and all(Path(path).is_file() for path in IMPORTS) and os.environ.get('SPIKE_BAZEL'), 'requires pinned Nix SDK imports and Bazel')
    def test_bazel_sdk_filegroup_materializes_import_bytes(self):
        output = Path(tempfile.mkdtemp(prefix='nix-import-declarations-')).resolve()
        shutil.copyfile(ROOT/'bazel/msbuild.bzl', output/'msbuild.bzl')
        (output/'BUILD.bazel').write_text('')
        (output/'MODULE.bazel').write_text('module(name="nix_import_test")\nlocal_dotnet_sdk = use_repo_rule("//:msbuild.bzl", "local_dotnet_sdk")\nlocal_dotnet_sdk(name="dotnet", path='+json.dumps(SDK)+', external_imports='+json.dumps(IMPORTS)+')\n')
        base = output/'base'
        result = subprocess.run([os.environ['SPIKE_BAZEL'],'--batch','--nohome_rc','--noworkspace_rc','--output_base='+str(base),'cquery','@dotnet//:files','--output=files','--noshow_progress'], cwd=output, capture_output=True,text=True,timeout=180)
        (output/'analysis.log').write_text(result.stdout+result.stderr)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        for index, source in enumerate(IMPORTS):
            self.assertIn('imports/'+str(index),result.stdout)
            matches = list((base/'external').glob('*/imports/'+str(index)))
            self.assertEqual(len(matches),1)
            self.assertEqual(hashlib.sha256(matches[0].read_bytes()).hexdigest(),hashlib.sha256(Path(source).read_bytes()).hexdigest())
        print('Nix SDK import evidence: '+str(output),flush=True)


if __name__ == '__main__': unittest.main()
