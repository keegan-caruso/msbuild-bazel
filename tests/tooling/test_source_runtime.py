"""Standalone runtime acquisition and nested Bazel invocation controls."""
import hashlib
import json
import os
import socket
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from source_runtime.common import stage_source, digest, read_recipe, owned_output, save, selected_bazel_version, validate_bazel_version, project_cache_read_only
from source_runtime.linux import launcher, build_command
from source_runtime import apple
sys.path.insert(0, str(ROOT / 'tests/graph_build/upstream'))
from runtime_product_inventory import configure_sync, inventory
import runtime_source_compatibility as compatibility


class SourceRuntimeSetupTests(unittest.TestCase):
    def test_runtime_linker_adaptation_preserves_other_bytes_and_rejects_drift(self):
        original = b"prefix\nargBuilder.Append(new string('\\\\', numBackslash));\nsuffix\n"
        expected = b"prefix\nargBuilder.Append('\\\\', numBackslash);\nsuffix\n"
        with patch.object(compatibility, 'LINKER_SHA256', hashlib.sha256(original).hexdigest()):
            self.assertEqual(compatibility.compatible_source(compatibility.LINKER_DRIVER, original), expected)
            for changed in (original + b'changed', expected):
                with self.assertRaisesRegex(ValueError, 'source changed'):
                    compatibility.compatible_source(compatibility.LINKER_DRIVER, changed)
        self.assertEqual(compatibility.compatible_source('unrelated.cs', original), original)

    def test_project_cache_policy_is_strict_and_retains_owned_state(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(project_cache_read_only(), '0')
            self.assertEqual(project_cache_read_only({'projectCacheReadOnly': '1'}), '1')
        for value in ('0', '1'):
            with patch.dict(os.environ, {'RULES_MSBUILD_PROJECT_CACHE_READ_ONLY': value}):
                self.assertEqual(project_cache_read_only(), value)
                self.assertEqual(project_cache_read_only({'projectCacheReadOnly': value}), value)
                with self.assertRaisesRegex(ValueError, 'policy changed'):
                    project_cache_read_only({'projectCacheReadOnly': '1' if value == '0' else '0'})
        for value in ('', 'true', '2', ' 1'):
            with patch.dict(os.environ, {'RULES_MSBUILD_PROJECT_CACHE_READ_ONLY': value}):
                with self.assertRaisesRegex(ValueError, 'must be 0 or 1'):
                    project_cache_read_only()

    def test_saved_runtime_commands_retain_read_only_and_reject_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            save(base/'setup.json', dict(workspace=str(base/'workspace'),
                identity={'projectCacheReadOnly': '1'}, environment={}))
            with patch.dict(os.environ, {}, clear=True):
                _, _, env = build_command(base, 'build')
                self.assertEqual(env['RULES_MSBUILD_PROJECT_CACHE_READ_ONLY'], '1')
            with patch.dict(os.environ, {'RULES_MSBUILD_PROJECT_CACHE_READ_ONLY': '0'}):
                with self.assertRaisesRegex(ValueError, 'policy changed'):
                    build_command(base, 'run')

    def test_saved_runtime_commands_disable_ambient_msbuild_server(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            save(base/'setup.json', dict(workspace=str(base/'workspace'), environment={
                'DOTNET_CLI_USE_MSBUILD_SERVER': 'true', 'MSBUILDUSESERVER': '1'}))
            with patch.dict(os.environ, {'DOTNET_CLI_USE_MSBUILD_SERVER': 'true', 'MSBUILDUSESERVER': '1'}):
                for action in ('build', 'test', 'run'):
                    _, _, env = build_command(base, action)
                    self.assertEqual(env['DOTNET_CLI_USE_MSBUILD_SERVER'], 'false')
                    self.assertEqual(env['MSBUILDUSESERVER'], '0')

    def test_apple_setup_forwards_retained_project_cache_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base/'rules').mkdir()
            archive = base/'rules.tar'; archive.write_bytes(b'frozen')
            state = dict(version=1, kind='apple-source-runtime', requestedImage=None, cacheUrl=None,
                projectCacheReadOnly='1', bazelVersion=(ROOT/'.bazelversion').read_text().strip(),
                rulesSha256=digest(archive), id='owned', worker='worker', image='runtime@sha256:'+'a'*64)
            save(base/'setup.json', state)
            worker = dict(configuration=dict(labels={'rules-msbuild.source-runtime': 'owned'},
                image=dict(descriptor=dict(digest='sha256:'+'a'*64)), resources={'memoryInBytes': 8*1024**3}), status={'state': 'running'})
            args = SimpleNamespace(output=base, resume=True, native_toolchain=None, sandbox=None,
                registry=None, repository_cache=None, host_space_path=None, image=None, cache_url=None,
                source_archive=None)
            with patch.dict(os.environ, {}, clear=True), \
                 patch.object(apple.platform, 'machine', return_value='arm64'), \
                 patch.object(apple.shutil, 'which', return_value='container'), \
                 patch.object(apple, 'demo_helpers', return_value=SimpleNamespace(inspect=lambda name: worker)), \
                 patch.object(apple, 'run'), \
                 patch.object(apple.subprocess, 'Popen', side_effect=RuntimeError('captured')) as execute:
                with self.assertRaisesRegex(RuntimeError, 'captured'):
                    apple.setup(args)
                command = execute.call_args.args[0]
                self.assertIn('RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=1', command)
                self.assertEqual(command[command.index('RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=1')-1], '--env')

    def test_apple_memory_selection_is_frozen_and_matches_worker(self):
        self.assertEqual(apple.worker_memory({}), 8)
        self.assertEqual(apple.worker_memory({'workerMemoryGiB': 12}), 12)
        self.assertEqual(apple.worker_memory({'workerMemoryGiB': 12}, 12), 12)
        for invalid in (0, -1, '12', True):
            with self.assertRaisesRegex(ValueError, 'Invalid saved'):
                apple.worker_memory({'workerMemoryGiB': invalid})
        with self.assertRaisesRegex(ValueError, 'memory changed'):
            apple.worker_memory({}, 12)
        worker = {'configuration': {'resources': {'memoryInBytes': 12*1024**3}}}
        apple.validate_worker_memory(worker, 12)
        with self.assertRaisesRegex(ValueError, 'memory differs'):
            apple.validate_worker_memory(worker, 8)

    def test_apple_run_rejects_changed_memory_before_starting_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            save(base/'setup.json', dict(kind='apple-source-runtime', ready=True, id='owned',
                worker='worker', image='runtime@sha256:'+'a'*64, workerMemoryGiB=12))
            args = SimpleNamespace(output=base, test=False, worker_memory_gib=8)
            with patch.dict(os.environ, {}, clear=True), patch.object(apple, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'memory changed'):
                    apple.operate(args, [])
                run.assert_not_called()
            args.worker_memory_gib = None
            worker = dict(configuration=dict(labels={'rules-msbuild.source-runtime': 'owned'},
                image=dict(descriptor=dict(digest='sha256:'+'a'*64)),
                resources={'memoryInBytes': 8*1024**3}), status={'state': 'stopped'})
            with patch.dict(os.environ, {}, clear=True), patch.object(apple, 'run') as run, \
                 patch.object(apple, 'demo_helpers', return_value=SimpleNamespace(inspect=lambda name: worker)):
                with self.assertRaisesRegex(ValueError, 'memory differs'):
                    apple.operate(args, [])
                run.assert_not_called()

    def test_worker_memory_cli_rejects_invalid_values_and_linux_use(self):
        command = [sys.executable, str(ROOT/'scripts/setup-source-runtime.py'), '/unused']
        for value in ('0', '-1', '1.5', '12G'):
            result = subprocess.run(command + ['--worker-memory-gib', value], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('positive integer', result.stderr)
        help_result = subprocess.run(command + ['--help'], capture_output=True, text=True)
        self.assertIn('--worker-memory-gib', help_result.stdout)
        code = ('import platform,runpy,sys; platform.system=lambda: "Linux"; '
                'sys.argv=["setup-source-runtime.py", "/unused", "--worker-memory-gib", "12"]; '
                'runpy.run_path(sys.argv[0], run_name="__main__")')
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT/'scripts', capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Apple Container setup options', result.stderr)

    def test_apple_relay_freezes_socket_and_validates_url_and_mount(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = str((Path(temporary) / 'relay.sock').resolve())
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(path)
                with patch.dict(os.environ, {'RULES_MSBUILD_SHARED_CACHE_SOCKET': path}, clear=True):
                    self.assertEqual(apple.cache_socket('https://cache.example:8443'), path)
                    for url in ('http://cache.example', 'https://127.0.0.1', 'https://user:pass@cache.example', 'https://cache.example/?token=x', 'https://cache.example/#fragment'):
                        with self.assertRaises(ValueError):
                            apple.cache_socket(url)
                    with self.assertRaisesRegex(ValueError, 'socket changed'):
                        apple.cache_socket('https://cache.example', {})
                with patch.dict(os.environ, {}, clear=True):
                    state = {'cacheSocket': path}
                    self.assertEqual(apple.cache_socket('https://cache.example', state), path)
                    self.assertIsNone(apple.cache_socket(None, {}))
                worker = {'configuration': {'mounts': [{'source': path, 'destination': apple.RELAY_SOCKET}]}}
                apple.validate_relay_mount(worker, path)
                worker['configuration']['mounts'][0]['source'] = '/different'
                with self.assertRaisesRegex(ValueError, 'mount differs'):
                    apple.validate_relay_mount(worker, path)
            Path(path).unlink()
            with patch.dict(os.environ, {'RULES_MSBUILD_SHARED_CACHE_SOCKET': path}, clear=True):
                with self.assertRaisesRegex(ValueError, 'existing host UNIX socket'):
                    apple.cache_socket('https://cache.example')

    def test_apple_setup_mounts_socket_before_extract_and_relay(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            path = str(base/'relay.sock')
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(path)
                (base/'rules').mkdir()
                archive = base/'rules.tar'; archive.write_bytes(b'frozen')
                state = dict(version=1, kind='apple-source-runtime', requestedImage=None,
                    cacheUrl='https://cache.example', cacheSocket=path, workerMemoryGiB=12,
                    bazelVersion=(ROOT/'.bazelversion').read_text().strip(), rulesSha256=digest(archive),
                    id='owned', worker='worker', image='runtime@sha256:'+'a'*64)
                save(base/'setup.json', state)
                args = SimpleNamespace(output=base, resume=True, native_toolchain=None, sandbox=None,
                    registry=None, repository_cache=None, host_space_path=None, image=None, cache_url=None,
                    source_archive=None, worker_memory_gib=12)
                with patch.dict(os.environ, {}, clear=True), \
                     patch.object(apple.platform, 'machine', return_value='arm64'), \
                     patch.object(apple.shutil, 'which', return_value='container'), \
                     patch.object(apple, 'demo_helpers', return_value=SimpleNamespace(inspect=lambda name: None)), \
                     patch.object(apple, 'run') as run, \
                     patch.object(apple.subprocess, 'Popen', side_effect=RuntimeError('captured')):
                    with self.assertRaisesRegex(RuntimeError, 'captured'):
                        apple.setup(args)
                calls = [call.args[0] for call in run.call_args_list]
                self.assertIn(path+':'+apple.RELAY_SOCKET, calls[0])
                self.assertEqual(calls[0][calls[0].index('--memory')+1], '12G')
                self.assertEqual(calls[2][3], 'tar')
                self.assertEqual(calls[3][:4], ['container', 'exec', 'worker', 'sh'])

    def test_apple_relay_is_started_after_restoring_owned_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            path = str((base/'relay.sock').resolve())
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(path)
                state = dict(kind='apple-source-runtime', ready=True, id='owned', worker='worker',
                    image='runtime@sha256:'+'a'*64, cacheSocket=path, cacheUrl='https://cache.example')
                save(base/'setup.json', state)
                worker = dict(configuration=dict(labels={'rules-msbuild.source-runtime': 'owned'},
                    image=dict(descriptor=dict(digest='sha256:'+'a'*64)),
                    mounts=[dict(source=path, destination=apple.RELAY_SOCKET)], resources={'memoryInBytes': 8*1024**3}), status={'state': 'stopped'})
                with patch.dict(os.environ, {}, clear=True), \
                     patch.object(apple, 'demo_helpers', return_value=SimpleNamespace(inspect=lambda name: worker)), \
                     patch.object(apple, 'run') as run, \
                     patch.object(apple.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
                    self.assertEqual(apple.operate(SimpleNamespace(output=base, test=False), []), 0)
                self.assertEqual(run.call_args_list[0].args[0], ['container', 'start', 'worker'])
                command = run.call_args_list[1].args[0]
                self.assertEqual(command[:4], ['container', 'exec', 'worker', 'sh'])
                self.assertEqual(command[-1], 'https://cache.example')
                self.assertIn('kill "$pid"', command[5])
                self.assertIn('rm -f "$ready" "$pidfile"', command[5])

    def test_apple_relay_failed_start_and_timeout_remove_owned_state(self):
        with patch.object(apple, 'run') as run:
            apple.start_relay('worker', 'https://cache.example')
        original = run.call_args.args[0][5]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for mode in ('fail', 'timeout'):
                fake = root/'fake-python'
                fake.write_text('#!/bin/sh\n' + ('exit 7\n' if mode == 'fail' else 'echo $$ > "'+str(root/'child')+'"\nexec sleep 30\n'))
                fake.chmod(0o755)
                script = original.replace('/tmp/rules-msbuild-source-runtime-relay', str(root/'relay'))
                script = script.replace('nohup python3 ', 'nohup '+str(fake)+' ')
                script = script.replace('seq 1 100', 'seq 1 2')
                result = subprocess.run(['sh', '-c', script, 'relay', 'https://cache.example'], capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root/'relay.pid').exists())
                self.assertFalse((root/'relay.ready').exists())
                if mode == 'timeout':
                    self.assertIn('timed out', result.stderr)
                    pid = int((root/'child').read_text())
                    with self.assertRaises(ProcessLookupError):
                        os.kill(pid, 0)

    def test_bazel_selection_and_resume_identity(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(selected_bazel_version(), (ROOT/'.bazelversion').read_text().strip())
        with patch.dict(os.environ, {'USE_BAZEL_VERSION': 'experimental'}):
            self.assertEqual(selected_bazel_version(), 'experimental')
            validate_bazel_version({'bazelVersion': 'experimental'})
            with self.assertRaisesRegex(ValueError, 'Bazel version changed'):
                validate_bazel_version({'bazelVersion': 'old'})
            with self.assertRaisesRegex(ValueError, 'Bazel version changed'):
                validate_bazel_version({})

    def test_apple_resume_rejects_bazel_override_before_container_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            save(base/'setup.json', dict(version=1, kind='apple-source-runtime',
                requestedImage=None, cacheUrl=None, bazelVersion='old'))
            args = SimpleNamespace(output=base, resume=True, native_toolchain=None, sandbox=None,
                registry=None, repository_cache=None, host_space_path=None, image=None, cache_url=None)
            with patch.object(apple.platform, 'machine', return_value='arm64'), \
                 patch.object(apple.shutil, 'which', return_value='container'), \
                 patch.dict(os.environ, {'USE_BAZEL_VERSION': 'new'}), \
                 patch.object(apple, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'Bazel version changed'):
                    apple.setup(args)
                run.assert_not_called()
            self.assertEqual(json.loads((base/'setup.json').read_text())['bazelVersion'], 'old')

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
            launcher(script, binary, 'file:///registry with spaces', base/'acquisition cache', cache, read_only='1')
            result = subprocess.check_output([script,'--output_base=/base with spaces','run','//:sync','--','--check'],text=True)
            arguments = json.loads(result)
            self.assertEqual(arguments[:2], ['--output_base=/base with spaces','run'])
            self.assertIn('--registry=file:///registry with spaces',arguments)
            self.assertIn('--remote_cache=' + cache,arguments)
            self.assertIn('--remote_max_connections=8', arguments)
            self.assertIn('--remote_timeout=60s', arguments)
            self.assertIn('--action_env=RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=1', arguments)
            self.assertFalse(any(arg.startswith('--remote_upload_local_results') for arg in arguments))
            self.assertIn('--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + cache,arguments)
            self.assertEqual(arguments[-3:],['//:sync','--','--check'])
            self.assertFalse(marker.exists())
            self.assertEqual(json.loads(subprocess.check_output([script,'--version'],text=True)),['--version'])
            launcher(script, binary, None, None, None)
            uncached = json.loads(subprocess.check_output([script, 'build', '//:target'], text=True))
            self.assertFalse(any(arg.startswith(('--remote_cache=', '--remote_cache_async=', '--remote_max_connections=', '--remote_timeout=')) for arg in uncached))

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
            state=dict(projectCacheReadOnly='1',kind='apple-source-runtime',ready=True,id='owned',worker='owned-worker',image='runtime@sha256:'+'a'*64)
            save(base/'setup.json',state)
            worker={'configuration':{'labels':{'rules-msbuild.source-runtime':'owned'},'image':{'descriptor':{'digest':'sha256:'+'a'*64}},'resources':{'memoryInBytes':8*1024**3}},'status':{'state':'stopped'}}
            with patch.object(apple,'demo_helpers',return_value=SimpleNamespace(inspect=lambda name:worker)), patch.object(apple,'run') as action, patch.object(apple.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as execute:
                self.assertEqual(apple.operate(SimpleNamespace(output=base,test=False),['--test','argument with spaces']),0)
                action.assert_called_once_with(['container','start','owned-worker'])
                self.assertIn('RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=1', execute.call_args.args[0])
                self.assertEqual(execute.call_args.args[0][-4:],['--run','--','--test','argument with spaces'])

    def test_run_uses_the_prepared_workspace_and_forwards_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base/'setup.json').write_text(json.dumps(dict(workspace=str(base/'workspace'),environment={'USE_BAZEL_VERSION':'9.3.2'})))
            command,cwd,env=build_command(base,'run',['--describe-runtime','argument with spaces'])
            self.assertEqual(cwd,base/'workspace')
            self.assertEqual(command[-3:],['--','--describe-runtime','argument with spaces'])
            self.assertIn('//:app',command)
            self.assertEqual(env['USE_BAZEL_VERSION'],'9.3.2')
            test,_,_=build_command(base,'test')
            self.assertIn('--nocache_test_results',test)
            self.assertIn('//:runtime_test',test)


if __name__ == '__main__':
    unittest.main()
