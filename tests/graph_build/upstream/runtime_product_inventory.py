"""Resolve the pinned shared-framework product with upstream MSBuild targets.

This is one-time source qualification. Package acquisition has already completed;
all queries restore privately from the declared closed archive inventory.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def inventory(source, feed, sdk, destination, mapping_path, log_directory):
    required = json.loads(subprocess.check_output([str(sdk/'dotnet'), 'msbuild',
        str(source/'src/libraries/NetCoreAppLibrary.props'), '-nologo', '-getItem:NetCoreAppLibrary'], text=True))
    assemblies = sorted(item['Identity'] + '.dll' for item in required['Items']['NetCoreAppLibrary'])
    if len(assemblies) != len(set(assemblies)) or len(assemblies) != 172:
        raise ValueError('Pinned upstream framework membership changed')
    with tempfile.TemporaryDirectory(prefix='runtime-product-inventory-') as temporary:
        scratch = Path(temporary).resolve()
        root = scratch/'source'
        shutil.copytree(source, root, ignore=shutil.ignore_patterns('bazel-*', '.git', '.nuget', 'artifacts'))
        (root/'NuGet.config').write_text('<configuration><packageSources><clear/><add key="closed" value="' + str(feed) + '"/></packageSources></configuration>')
        environment = dict(os.environ, DOTNET_ROOT=str(sdk), DOTNET_CLI_HOME=str(scratch/'home'), HOME=str(scratch/'home'),
            NUGET_PACKAGES=str(scratch/'packages'), NUGET_HTTP_CACHE_PATH=str(scratch/'http'),
            MSBUILDDISABLENODEREUSE='1', DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_NOLOGO='1')
        properties = ['-p:Configuration=Release', '-p:TargetOS=linux', '-p:TargetArchitecture=arm64',
            '-p:UseLocalTargetingRuntimePack=false', '-p:RestoreUseStaticGraphEvaluation=false']
        project = 'src/libraries/sfx-src.proj'
        with (log_directory/'product-restore.log').open('w') as log:
            subprocess.run([str(sdk/'dotnet'), 'restore', project, *properties, '-p:NuGetAudit=false',
                '-p:RestoreLockedMode=true', '-p:RestoreFallbackFolders=', '-p:RestoreAdditionalProjectFallbackFolders='],
                cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        def query(project, target, items, props=(), framework=None):
            command = [str(sdk/'dotnet'), 'msbuild', project, '-nologo', '-verbosity:quiet', *properties,
                '-t:' + target, '-getItem:' + ','.join(items)]
            if props:
                command += ['-getProperty:' + ','.join(props)]
            if framework:
                command += ['-p:TargetFramework=' + framework, '-p:BuildAllProjects=true']
            result = subprocess.run(command, cwd=root, env=environment, text=True, capture_output=True)
            if result.returncode:
                raise ValueError('Upstream product query failed: ' + project + '\n' + result.stdout + result.stderr)
            # MSBuild's query output is JSON; do not parse project XML or reimplement
            # NuGet's nearest-framework selection and BinPlace conditions.
            return json.loads(result.stdout)
        resolved = query(project, 'ResolveP2PReferences', ['ProjectReference'])
        references = resolved['Items']['ProjectReference']
        (log_directory/'product-selection.json').write_text(json.dumps(resolved, indent=2) + '\n')
        def producer(item):
            path = Path(item['FullPath'])
            project = str(path.relative_to(root))
            framework = item.get('NearestTargetFramework') or item.get('TargetFrameworks')
            if not framework or ';' in framework:
                raise ValueError('Upstream did not select one framework: ' + project)
            # CoreLib is shipped by liveBuilds.targets directly; it does not
            # import the libraries' binplace SDK target.
            target = 'GetTargetPath' if project.startswith('src/coreclr/') else 'GetBinPlaceTargetFramework'
            result = query(project, target, ['BinPlaceDir'],
                ['TargetFileName', 'GenerateDocumentationFile', 'DebugType'], framework)
            name = result['Properties']['TargetFileName']
            copies = []
            extensions = ['.dll']
            if result['Properties']['DebugType'] not in ['none', 'embedded']:
                extensions.append('.pdb')
            if result['Properties']['GenerateDocumentationFile'].lower() == 'true':
                extensions.append('.xml')
            for placement in result['Items']['BinPlaceDir']:
                directory = Path(placement['Identity'].replace('\\', '/'))
                if not directory.is_absolute():
                    directory = path.parent/directory
                relative = str(directory.resolve().relative_to(root))
                copies += [relative + '/' + Path(name).stem + extension for extension in extensions]
            single = item.get('HasSingleTargetFramework', '').lower()
            if single not in ['true', 'false']:
                raise ValueError('Missing upstream single-target classification: ' + project)
            return name, dict(project=project, framework=framework, singleTarget=single == 'true'), sorted(set(copies))
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(producer, references))
        if sorted(name for name, _, _ in rows) != assemblies:
            raise ValueError('Resolved product producers differ from upstream framework membership')
        mapping = json.loads(mapping_path.read_text())
        for name, producer, copies in rows:
            binding = mapping['projects'].setdefault(producer['project'], {})
            configured = binding.setdefault('frameworkOverrides', {}).setdefault(producer['framework'], {})
            configured['outputFiles'] = sorted(set(configured.get('outputFiles', binding.get('outputFiles', mapping['projectDefaults'].get('outputFiles', [])))) | set(copies))
        mapping_path.write_text(json.dumps(mapping, indent=2) + '\n')
        destination.write_text(json.dumps(dict(version='10.0.0', platform='linux-arm64', root=project,
            assemblies=assemblies, producers={name:producer for name,producer,_ in rows}), indent=2) + '\n')


def configure_sync(descriptor, mapping_path):
    product = json.loads(descriptor.read_text())
    entries = sorted(value['project'] for value in product['producers'].values())
    if len(entries) != len(set(entries)):
        raise ValueError('Ambiguous source product project roots')
    # Preserve the upstream TraversalGlobalProperties while declaring its
    # resolved references as explicit roots of the normal MSBuild graph action.
    overrides = {value['project']: dict(BuildAllProjects='true',
        **({} if value['singleTarget'] else {'TargetFramework':value['framework']}))
        for value in product['producers'].values()}
    mapping = json.loads(mapping_path.read_text())
    mapping['entryProperties'] = overrides
    mapping_path.write_text(json.dumps(mapping, indent=2) + '\n')
    return entries, overrides
