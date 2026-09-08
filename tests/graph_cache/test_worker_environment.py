"""Focused restore regression: cached MSBuild workers must not leak CLI homes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from probe_graph_cache import cache_environment, restore_source, run_logged
from prepare_graph import DOTNET_ROOT, prepare
from probe_graph_execution import write_fixture


class CacheWorkerEnvironmentAcceptance(unittest.TestCase):
    def test_wrapper_workers_cannot_change_probe_restore_configuration(self):
        output = Path(tempfile.mkdtemp(prefix='msbuild-cache-worker-')).resolve()
        print('Cache worker evidence: ' + str(output), file=sys.stderr)
        seed = output / 'wrapper-seed'
        write_fixture(seed)
        seed_environment = dict(os.environ)
        seed_environment.pop('MSBUILDDISABLENODEREUSE', None)
        result = subprocess.run(['bash', str(ROOT / 'scripts/dotnet.sh'), 'msbuild',
            str(seed / 'build.proj'), '-t:Restore', '-p:Configuration=Release', '-m:4',
            '-nodeReuse:true', '-nologo'], cwd=ROOT, env=seed_environment,
            text=True, capture_output=True, timeout=180)
        (output / 'wrapper-seed.log').write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        run_logged(output, 'exporter-build', [DOTNET_ROOT / 'dotnet', 'build',
            ROOT / 'tools/GraphExport', '-c', 'Release', '--nologo'], ROOT)
        restored_states = []
        for index in range(3):
            source = output / f'consumer-{index}'
            write_fixture(source)
            (source / '.nuget/packages').mkdir(parents=True)
            restore_source(output, source, f'restore-{index}')
            for project in ('Shared', 'Left', 'Right', 'App'):
                assets = json.loads((source / f'src/{project}/obj/project.assets.json').read_text())
                configurations = assets['project']['restore']['configFilePaths']
                self.assertIn(str(source / 'NuGet.Config'), configurations)
                self.assertIn(str(output / 'home/.nuget/NuGet/NuGet.Config'), configurations)
                self.assertNotIn(str(ROOT / '.cache/dotnet-home/.nuget/NuGet/NuGet.Config'), configurations)
            # Run actual preparation children with the identical explicit environment,
            # then compare the restore action inputs across fresh source locations.
            manifest = output / f'manifest-{index}.json'
            request = output / f'request-{index}.json'
            request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(source),
                dotnetRoot=str(DOTNET_ROOT), sdkVersion='10.0.400',
                packageRoot=str(source / '.nuget/packages'),
                entryPoints=[dict(project='build.proj', globalProperties={'Configuration':'Release'})],
                output=str(manifest))))
            run_logged(output, f'export-{index}', [DOTNET_ROOT / 'dotnet',
                ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], source)
            generated = output / f'generated-{index}'
            prepare(source, manifest, generated, environment=cache_environment(output, source))
            restored_states.append({p.name: p.read_text() for p in (generated / 'restore').glob('*.json')})
        self.assertEqual(len(restored_states[0]), 4)
        self.assertEqual(restored_states[0], restored_states[1])
        self.assertEqual(restored_states[0], restored_states[2])
