"""Standalone runtime acquisition and nested Bazel invocation controls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from source_runtime.common import stage_source, digest, read_recipe, owned_output, save
from source_runtime.linux import launcher, build_command
from source_runtime import apple
sys.path.insert(0, str(ROOT / 'tests/graph_build/upstream'))
from runtime_product_inventory import configure_sync, inventory


class SourceRuntimeSetupTests(unittest.TestCase):
    def test_restore_reuse_reviews_only_pinned_linux_compile_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'mappings.json'
            command = [sys.executable, str(ROOT/'tests/graph_build/upstream/runtime_contract.py'),
                str(output), '--restore-reuse']
            rejected = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(rejected.returncode, 2)
            self.assertIn('--prepared-restore and --platform=linux-arm64', rejected.stderr)
            self.assertFalse(output.exists())
            subprocess.run(command + ['--prepared-restore', '--platform=linux-arm64'], check=True)
            mapping = json.loads(output.read_text())
            self.assertEqual(mapping['restoreReuseInputs'], [
                'src/libraries/System.IO.Pipelines/ref/System.IO.Pipelines.cs',
                'src/libraries/System.IO.Pipelines/src/System/IO/Pipelines/PipeOptions.cs'])
            self.assertNotIn('evaluationReuseInputs', mapping['projectDefaults'])

    def test_runtime_contract_declares_late_vb_resource_and_outer_tool_roles(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'mappings.json'
            subprocess.run([sys.executable, str(ROOT/'tests/graph_build/upstream/runtime_contract.py'), str(output),
                '--platform=linux-arm64', '--prepared-restore', '--resolve-references'], check=True)
            mapping = json.loads(output.read_text())
            project = 'src/libraries/Microsoft.VisualBasic.Core/src/Microsoft.VisualBasic.Core.vbproj'
            binding = mapping['projects'][project]
            for variant in [binding] + list(binding.get('frameworkOverrides', {}).values()):
                self.assertFalse(variant['referenceBoundary'])
                self.assertIn(project.removesuffix('Microsoft.VisualBasic.Core.vbproj')+'ILLink/ILLink.Descriptors.Windows.xml',
                    variant['documents'][project]['inputs'])
            generator = mapping['projects']['src/libraries/System.Text.Json/src/System.Text.Json.csproj']
            self.assertTrue(generator['implementationDependencies'])
            self.assertEqual(generator['frameworkOverrides']['']['implementationDependencies'], [])

    def test_product_inventory_keeps_project_metadata_when_reading_binplace_items(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base/'source'; source.mkdir()
            mapping = base/'mappings.json'
            mapping.write_text(json.dumps(dict(projectDefaults=dict(outputFiles=[]), projects={})))
            names = ['System%03d' % index for index in range(172)]
            def query(command, **kwargs):
                root = kwargs['cwd']
                if command[1] == 'restore':
                    return SimpleNamespace(returncode=0)
                if '-t:ResolveP2PReferences' in command:
                    items = [dict(FullPath=str(root/(name+'.csproj')), NearestTargetFramework='net10.0',
                        HasSingleTargetFramework='true' if index == 0 else 'false') for index,name in enumerate(names)]
                    result = dict(Items=dict(ProjectReference=items))
                else:
                    name = Path(command[2]).stem
                    result = dict(Items=dict(BinPlaceDir=[dict(Identity=str(root/'artifacts/bin/runtime'))]),
                        Properties=dict(TargetFileName=name+'.dll', GenerateDocumentationFile='false', DebugType='none'))
                return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr='')
            required = json.dumps(dict(Items=dict(NetCoreAppLibrary=[dict(Identity=name) for name in names])))
            with patch('runtime_product_inventory.subprocess.check_output', return_value=required), patch('runtime_product_inventory.subprocess.run', side_effect=query):
                inventory(source, base/'feed', base/'sdk', base/'product.json', mapping, base)
            product = json.loads((base/'product.json').read_text())
            self.assertTrue(product['producers']['System000.dll']['singleTarget'])
            self.assertFalse(product['producers']['System001.dll']['singleTarget'])
            configured = json.loads(mapping.read_text())['projects']['System000.csproj']['frameworkOverrides']['net10.0']
            self.assertEqual(configured['outputFiles'], ['artifacts/bin/runtime/System000.dll'])

    def test_product_roots_keep_single_target_frameworks_project_owned(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)
            descriptor=base/'product.json'
            descriptor.write_text(json.dumps({'producers':{
                'Single.dll':dict(project='Single/Single.csproj',framework='net10.0',singleTarget=True),
                'Multi.dll':dict(project='Multi/Multi.csproj',framework='net10.0-linux',singleTarget=False)}}))
            mapping=base/'mappings.json'
            mapping.write_text(json.dumps({'entryProperties':{'old/dirs.proj':{'TargetFramework':'net10.0-linux'}}}))
            entries,overrides=configure_sync(descriptor,mapping)
            self.assertEqual(entries,['Multi/Multi.csproj','Single/Single.csproj'])
            self.assertNotIn('TargetFramework',overrides['Single/Single.csproj'])
            self.assertEqual(overrides['Multi/Multi.csproj']['TargetFramework'],'net10.0-linux')
            self.assertEqual(json.loads(mapping.read_text())['entryProperties'],overrides)

    def test_qualification_cache_requires_an_explicit_endpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)
            environment=dict(os.environ)
            environment.pop('RULES_MSBUILD_PROJECT_CACHE_URL',None)
            result=subprocess.run([sys.executable,str(ROOT/'tests/graph_build/upstream/runtime_downloaded_prepare.py'),
                str(base/'source.tar.gz'),str(base/'output'),'--qualification-cache'],env=environment,
                text=True,capture_output=True)
            self.assertEqual(result.returncode,2)
            self.assertIn('--qualification-cache requires RULES_MSBUILD_PROJECT_CACHE_URL',result.stderr)
            self.assertFalse((base/'output').exists())

    def test_recipe_matches_bootstrap_pins(self):
        recipe = read_recipe()
        pins = json.loads((ROOT / 'scripts/toolchains.json').read_text())
        self.assertEqual(recipe['sdk']['version'], pins['dotnet']['version'])
        self.assertEqual(recipe['source']['revision'], '60629d14374c56f1cb51819049ad1fa529307f8d')

    def test_acquisition_verifies_supplied_and_retained_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source, destination = base/'source', base/'download'
            source.write_bytes(b'pinned source')
            expected = digest(source)
            stage_source(destination, expected, source)
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            # A retained source is checked again, even though no download runs.
            destination.unlink()
            destination.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'Retained download changed'):
                stage_source(destination, expected, source)
            destination.unlink()
            with self.assertRaisesRegex(ValueError, 'Supplied source archive differs'):
                stage_source(destination, '0'*64, source)
            self.assertFalse(destination.exists())

    def test_interrupted_acquisition_cannot_overwrite_the_supplied_inode(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)
            original=base/'original';original.write_bytes(b'keep original')
            destination=base/'download.tar.gz'
            os.link(original, destination.with_suffix('.partial'))
            supplied=base/'supplied'; supplied.write_bytes(b'new source')
            stage_source(destination,digest(supplied),supplied)
            self.assertEqual(original.read_bytes(),b'keep original')
            self.assertEqual(destination.read_bytes(),b'new source')

    def test_resume_requires_owned_state_and_preserves_unowned_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)
            unowned=base/'unowned';unowned.mkdir()
            sentinel=unowned/'keep';sentinel.write_text('user data')
            with self.assertRaisesRegex(ValueError,'unowned'):
                owned_output(unowned,True,'linux-source-runtime')
            self.assertEqual(sentinel.read_text(),'user data')
            owned=base/'owned'
            self.assertIsNone(owned_output(owned,False,'linux-source-runtime'))
            state=dict(version=1,kind='linux-source-runtime',completed=['tools'])
            save(owned/'setup.json',state)
            self.assertEqual(owned_output(owned,True,'linux-source-runtime'),state)
            with self.assertRaisesRegex(ValueError,'another workflow'):
                owned_output(owned,True,'apple-source-runtime')
            self.assertEqual(owned_output(owned,False,'linux-source-runtime'),state)

    def test_automatic_apple_resume_rejects_changed_rules_and_options_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)
            state=dict(version=1,kind='apple-source-runtime',sourceIdentity='old',requestedImage='pinned-image',cacheUrl='http://cache')
            save(base/'setup.json',state)
            sentinel=base/'keep';sentinel.write_text('retained')
            def arguments():
                return SimpleNamespace(output=base,resume=False,native_toolchain=None,sandbox=None,registry=None,
                    repository_cache=None,host_space_path=None,image=None,cache_url=None)
            with patch.object(apple.platform,'machine',return_value='arm64'), patch.object(apple.shutil,'which',return_value='container'), \
                 patch.object(apple,'demo_helpers'), patch.object(apple,'rules_identity',return_value='current'):
                with self.assertRaisesRegex(ValueError,'matching owned setup inputs'):
                    apple.setup(arguments())
                state['sourceIdentity']='current'
                save(base/'setup.json',state)
                args=arguments();args.cache_url='http://changed-cache'
                with self.assertRaisesRegex(ValueError,'options changed'):
                    apple.setup(args)
            self.assertEqual(sentinel.read_text(),'retained')
            self.assertEqual(json.loads((base/'setup.json').read_text()),state)

    def test_nested_bazel_options_preserve_arguments_and_do_not_execute_shell(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            binary = base/'fake bazelisk'
            binary.write_text('#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            binary.chmod(0o755)
            script = base/'wrapper'
            marker = base/'injected'
            cache = 'https://cache.invalid/$(touch ' + str(marker) + ')'
            launcher(script, binary, 'file:///registry with spaces', base/'acquisition cache', cache)
            result = subprocess.check_output([script,'--output_base=/base with spaces','run','//:sync','--','--check'],text=True)
            arguments = json.loads(result)
            self.assertEqual(arguments[:2], ['--output_base=/base with spaces','run'])
            self.assertIn('--registry=file:///registry with spaces',arguments)
            self.assertIn('--remote_cache=' + cache,arguments)
            self.assertIn('--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + cache,arguments)
            self.assertEqual(arguments[-3:],['//:sync','--','--check'])
            self.assertFalse(marker.exists())
            self.assertEqual(json.loads(subprocess.check_output([script,'--version'],text=True)),['--version'])

    def test_apple_run_requires_owned_worker_and_pinned_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)
            state=dict(kind='apple-source-runtime',ready=True,id='owned',worker='owned-worker',image='runtime@sha256:'+'a'*64)
            save(base/'setup.json',state)
            args=SimpleNamespace(output=base,test=False)
            for label, digest, message in [('other','a'*64,'ownership'),('owned','b'*64,'image differs')]:
                worker={'configuration':{'labels':{'rules-msbuild.source-runtime':label},'image':{'descriptor':{'digest':'sha256:'+digest}}},'status':{'state':'stopped'}}
                helpers=SimpleNamespace(inspect=lambda name:worker)
                with patch.object(apple,'demo_helpers',return_value=helpers), patch.object(apple,'run') as action, patch.object(apple.subprocess,'run') as execute:
                    with self.assertRaisesRegex(ValueError,message):
                        apple.operate(args,[])
                    action.assert_not_called()
                    execute.assert_not_called()

    def test_apple_run_starts_only_the_owned_worker_and_preserves_app_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)
            state=dict(kind='apple-source-runtime',ready=True,id='owned',worker='owned-worker',image='runtime@sha256:'+'a'*64)
            save(base/'setup.json',state)
            worker={'configuration':{'labels':{'rules-msbuild.source-runtime':'owned'},'image':{'descriptor':{'digest':'sha256:'+'a'*64}}},'status':{'state':'stopped'}}
            with patch.object(apple,'demo_helpers',return_value=SimpleNamespace(inspect=lambda name:worker)), patch.object(apple,'run') as action, patch.object(apple.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as execute:
                self.assertEqual(apple.operate(SimpleNamespace(output=base,test=False),['--test','argument with spaces']),0)
                action.assert_called_once_with(['container','start','owned-worker'])
                self.assertEqual(execute.call_args.args[0][-4:],['--run','--','--test','argument with spaces'])

    def test_run_uses_the_prepared_workspace_and_forwards_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base/'setup.json').write_text(json.dumps(dict(workspace=str(base/'workspace'),environment={'USE_BAZEL_VERSION':'9.3.0'})))
            command,cwd,env=build_command(base,'run',['--describe-runtime','argument with spaces'])
            self.assertEqual(cwd,base/'workspace')
            self.assertEqual(command[-3:],['--','--describe-runtime','argument with spaces'])
            self.assertIn('//:app',command)
            self.assertEqual(env['USE_BAZEL_VERSION'],'9.3.0')
            test,_,_=build_command(base,'test')
            self.assertIn('--nocache_test_results',test)
            self.assertIn('//:runtime_test',test)


if __name__ == '__main__':
    unittest.main()
