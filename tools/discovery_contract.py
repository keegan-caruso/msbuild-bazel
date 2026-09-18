"""Fail-closed qualification of the first, path-bound SDK discovery slice.

This is a capture/validation boundary, not a preparation cache. See
docs/discovery-contract.md for the deliberately restricted authored XML grammar.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
from xml.parsers import expat

import graph_packages
from preparation_identity import IdentityError, capture, compare, digest, tree_snapshot, validate

ROOT = Path(__file__).resolve().parents[1]
POLICY = 'darwin-arm64-net10-discovery-v1'
EPOCH = 946684800
SDK = Path('/nix/store/f3kvj2nc26gn7rh5mnfnaa2dgy2p10v3-dotnet-sdk-10.0.400/share/dotnet')
PROPERTIES = {'TargetFramework', 'OutputType', 'AssemblyName', 'RootNamespace',
              'EnableDefaultCompileItems', 'Nullable', 'ImplicitUsings', 'LangVersion',
              'Version', 'OfficialBuildId', 'BuildStamp', 'Value'}
PROPERTIES |= {'Description', 'Authors', 'Copyright', 'AssemblyVersion', 'TargetFrameworks',
               'PackageTags', 'PackageIcon', 'PackageProjectUrl', 'PackageLicenseExpression',
               'IsAotCompatible', 'NoWarn', 'PolySharpIncludeRuntimeSupportedAttributes',
               'PolySharpExcludeGeneratedTypes', 'PackageReadmeFile', 'DisableImplicitFrameworkReferences',
               'DefineConstants', 'VersionPrefix', 'TreatWarningsAsErrors', 'SignAssembly',
               'AssemblyOriginatorKeyFile', 'CheckEolTargetFramework', 'GenerateDocumentationFile',
               'PublishRepositoryUrl', 'EmbedUntrackedSources', 'IncludeSymbols', 'SymbolPackageFormat'}
# Literal SDK switches used by the package-free scale fixture. They may not
# select tasks, paths or property functions; qualify only these exact values.
SDK_SWITCHES = {'UseAppHost': 'false', 'UseSharedCompilation': 'false',
                'EnableNETAnalyzers': 'false', 'Deterministic': 'true',
                'DisableTransitiveProjectReferences': 'true'}
# Optional discovery literal; not a required switch for the owned synthetic policy.
QUALIFIED_SDK_SWITCHES = dict(SDK_SWITCHES, DeterministicSourcePaths='false')
ITEMS = {'Compile', 'None', 'EmbeddedResource', 'Content', 'AdditionalFiles',
         'BazelExtraInput', 'ProjectReference', 'Reference', 'PackageReference', 'Using', 'RuntimeHostConfigurationOption'}
TEST_PACKAGES = json.loads((ROOT / 'tools/discovery-test-packages.json').read_text())
QUALIFIED_PACKAGES = {'polysharp/1.15.0', 'microsoft.net.illink.tasks/10.0.11'} | set(TEST_PACKAGES['packages'])
PACKAGE_IMPORTS = {'build/PolySharp.targets', 'buildTransitive/PolySharp.targets',
                   'build/Microsoft.NET.ILLink.Tasks.props', 'build/Microsoft.NET.ILLink.Analyzers.props',
                   'build/Microsoft.NET.ILLink.targets'}
SDK_IMPORTS = json.loads((ROOT / 'tools/discovery-sdk-imports.json').read_text())['imports']
CONTROLLER_FILES = ('discovery_contract.py', 'preparation_identity.py', 'graph_packages.py',
                    'pilot-package-policy.json', 'discovery-test-packages.json', 'discovery-sdk-imports.json', 'protected_store.py', 'preparation_source_update.py')
CONTROLLER_DIGEST = digest({name: (ROOT / 'tools' / name).read_text() for name in CONTROLLER_FILES})


def check_xml(path):
    """Accept an allowlisted grammar, never infer safety from a clean time scan.

    Imports are resolved by MSBuild, then every imported non-toolchain file is
    checked regardless of extension. The sealed namespace covers unhooked reads.
    """
    stack = []
    parser = expat.ParserCreate(namespace_separator='}')

    def reject(message):
        raise IdentityError(f'unsupported discovery XML: {path}:{parser.CurrentLineNumber}: {message}')

    def expression(value):
        # Decode MSBuild escapes before checking expression syntax.
        value = re.sub(r'%([0-9a-f]{2})', lambda m: chr(int(m[1], 16)), value, flags=re.I)
        # The selected upstream Serilog files use these exact pure expressions.
        # This does not admit other instance or static property functions.
        for pure in ("$(VersionPrefix.Substring(0,3))", "$(MSBuildProjectName.EndsWith('Tests'))",
                     "$([MSBuild]::IsTargetFrameworkCompatible('$(TargetFramework)', 'net7.0'))"):
            value = value.replace(pure, '')
        # Only simple property references are accepted. Even string instance
        # functions are excluded; no regex black-list of clock method names.
        value = re.sub(r'\$\([A-Za-z_][A-Za-z_0-9]*\)', '', value)
        if '$(' in value or '@(' in value or '%(' in value:
            reject('property functions, item transforms and metadata expressions are not qualified')

    def start(name, attrs):
        name = name.split('}')[-1]
        parent = stack[-1][0] if stack else None
        if parent is None:
            if name != 'Project' or set(attrs) - {'Sdk', 'ToolsVersion'}:
                reject('project attributes')
            if attrs.get('Sdk', 'Microsoft.NET.Sdk') != 'Microsoft.NET.Sdk':
                reject('SDK resolver')
            versions = {'Current', '14.0'} if path.name.endswith(('.nuget.g.props', '.nuget.g.targets')) else {'Current'}
            if attrs.get('ToolsVersion', 'Current') not in versions: reject('toolset')
        elif parent == 'Project':
            if name not in {'PropertyGroup', 'ItemGroup', 'Import', 'ImportGroup', 'Choose'}:
                reject(name)
        elif parent in {'Choose', 'When', 'Otherwise', 'ImportGroup'}:
            allowed = {'When', 'Otherwise'} if parent == 'Choose' else {'PropertyGroup', 'ItemGroup', 'Import', 'Choose'}
            if name not in allowed: reject(name)
        elif parent == 'PropertyGroup':
            # Restore-generated wrapper properties contain machine paths but
            # cannot extend target execution or choose arbitrary SDKs.
            generated = path.name.endswith(('.nuget.g.props', '.nuget.g.targets'))
            generated_names = {'RestoreSuccess', 'RestoreTool', 'ProjectAssetsFile', 'NuGetPackageRoot',
                               'NuGetPackageFolders', 'NuGetProjectStyle', 'NuGetToolVersion', 'PkgMicrosoft_NET_ILLink_Tasks', 'Pkgxunit_analyzers'}
            if name not in PROPERTIES and name not in QUALIFIED_SDK_SWITCHES and not (generated and name in generated_names): reject(name)
        elif parent == 'ItemGroup':
            generated = path.name.endswith(('.nuget.g.props', '.nuget.g.targets'))
            if name not in ITEMS and not (generated and name == 'SourceRoot'): reject(name)
        elif parent == 'EmbeddedResource' and name == 'LogicalName':
            pass
        else:
            # Metadata can change project-reference configuration or discovery
            # target hooks. Qualify such extensions separately.
            reject('nested metadata: ' + name)
        if name == 'RuntimeHostConfigurationOption' and attrs != {
                'Condition': "'$(PublishTrimmed)' == 'true'", 'Include': 'Serilog.Capturing.IsStructureValueSupported',
                'Value': 'false', 'Trim': 'true'}:
            reject('unqualified runtime configuration option')
        allowed_attrs = {'Condition', 'Label'}
        if name == 'Project': allowed_attrs |= {'Sdk', 'ToolsVersion'}
        if name == 'Import': allowed_attrs |= {'Project'}
        if parent == 'ItemGroup': allowed_attrs |= {'Include', 'Exclude', 'Remove', 'Update'}
        if name == 'None': allowed_attrs |= {'Pack', 'Visible', 'PackagePath'}
        if name == 'PackageReference': allowed_attrs |= {'Version', 'PrivateAssets'}
        if name == 'RuntimeHostConfigurationOption': allowed_attrs |= {'Value', 'Trim'}
        if set(attrs) - allowed_attrs: reject('attributes on ' + name)
        for value in attrs.values(): expression(value)
        stack.append((name, []))

    def end(name):
        _, fragments = stack.pop()
        value = ''.join(fragments)
        if name in QUALIFIED_SDK_SWITCHES and value.strip() != QUALIFIED_SDK_SWITCHES[name]:
            reject('unqualified SDK switch value: ' + name)
        expression(value)

    def doctype(*args): reject('DTD')
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = lambda value: stack[-1][1].append(value) if stack else None
    parser.StartDoctypeDeclHandler = doctype
    try:
        parser.Parse(path.read_bytes(), True)
    except expat.ExpatError as error:
        raise IdentityError('invalid discovery XML: ' + str(path)) from error


def seal(source, destination):
    """Copy without links and identify the exact supplied view, not an atomic checkout.

    Restore metadata is relocated as in preparation. Timestamp normalization is
    part of this operation's input semantics, not a claim about the live checkout.
    """
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.is_relative_to(source):
        raise IdentityError('stage must be outside source')
    before = tree_snapshot(source)
    if any(entry['kind'] == 'symlink' for entry in before['entries']):
        raise IdentityError('symlinks are not qualified for sealed workspace inputs')
    shutil.copytree(source, destination)
    after = tree_snapshot(source)
    if before != after:
        raise IdentityError('source changed while sealing')
    # Restore caches encode the input root. Never rewrite authored project bytes.
    for path in destination.rglob('*'):
        restore_metadata = path.name in {'project.assets.json', 'project.nuget.cache'} or path.name.endswith(('.nuget.g.props', '.nuget.g.targets', '.nuget.dgspec.json'))
        if path.is_file() and 'obj' in path.relative_to(destination).parts and restore_metadata:
            data = path.read_bytes()
            path.write_bytes(data.replace(str(source).encode(), str(destination).encode()))
    (destination / '.nuget/packages').mkdir(parents=True, exist_ok=True)
    for path in sorted(destination.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        os.utime(path, (EPOCH, EPOCH))
    os.utime(destination, (EPOCH, EPOCH))
    return before


def sandbox_profile(read_roots, output):
    quote = lambda value: json.dumps(str(value))
    # System libraries are tied to this same-host OS build. No user home,
    # general /private/tmp, arbitrary /nix/store or network access is allowed.
    runtime = [Path('/System/Library'), Path('/usr/lib'), Path('/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld'), Path('/System/Cryptexes/OS/System/Library/dyld')]
    ancestors = sorted({parent for path in [*read_roots, *runtime] for parent in Path(path).parents})
    reads = '\n'.join(f'(allow file-read* file-test-existence file-map-executable (subpath {quote(path)}))' for path in read_roots)
    metadata = '\n'.join(f'(allow file-read-metadata file-test-existence (literal {quote(path)}))' for path in ancestors)
    return f'''(version 1)
(deny default)
(allow process-exec process-fork signal sysctl-read mach-lookup)
(allow file-read* file-test-existence (literal "/"))
(allow file-read* file-test-existence file-map-executable (subpath "/System/Library") (subpath "/usr/lib")
  (subpath "/usr/share/icu")
  (subpath "/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld")
  (subpath "/System/Cryptexes/OS/System/Library/dyld")
  (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))
(allow file-write* (literal "/dev/null") (subpath {quote(output)}))
{reads}
{metadata}
'''


def controlled_environment(output):
    return dict(DOTNET_ROOT=str(SDK), DOTNET_HOST_PATH=str(SDK / 'dotnet'),
               HOME=str(output / 'home'), DOTNET_CLI_HOME=str(output / 'home'),
               TMPDIR=str(output / 'tmp'), NUGET_HTTP_CACHE_PATH=str(output / 'http'),
               PATH=str(SDK), TZ='UTC', LANG='en_US.UTF-8', LC_ALL='en_US.UTF-8',
               DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1',
               DOTNET_MULTILEVEL_LOOKUP='0', DOTNET_EnableDiagnostics='0',
               MSBUILDDISABLENODEREUSE='1', MSBuildEnableWorkloadResolver='false')

def validate_certificate(value):
    try:
        if (value['schemaVersion'] != 1 or value['policy'] != POLICY or value['eligible'] is not True or
                value['reuseEnabled'] is not False or value['operation'] != 'GraphExport' or value['timestampEpoch'] != EPOCH):
            raise IdentityError('unsupported discovery certificate')
        validate(value['identity'])
        if value['sha256'] != digest({k: v for k, v in value.items() if k != 'sha256'}):
            raise IdentityError('corrupt discovery certificate')
        for key in ('graphSha256', 'observationSha256'):
            if not re.fullmatch('[0-9a-f]{64}', value[key]): raise IdentityError('corrupt discovery certificate')
        if (not isinstance(value['externalAbsent'], list) or
                any(not isinstance(path, str) or not Path(path).is_absolute() for path in value['externalAbsent'])):
            raise IdentityError('invalid external negative observations')
    except (KeyError, TypeError) as error:
        raise IdentityError('incomplete discovery certificate') from error


@contextmanager
def qualified_view(source, state, entries, *, candidate=None, protected_store=None, candidate_graph=None, candidate_adapter=None):
    """Capture one supported full GraphExport invocation; production reuse stays off."""
    if candidate is not None: validate_certificate(candidate)
    if CONTROLLER_DIGEST != digest({name: (ROOT / 'tools' / name).read_text() for name in CONTROLLER_FILES}):
        raise IdentityError('discovery controller changed; start a fresh process')
    if platform.system() != 'Darwin' or platform.machine() != 'arm64' or not SDK.is_dir():
        raise IdentityError('unqualified host/toolchain')
    for entry in entries:
        if set(entry) != {'project', 'globalProperties'}:
            raise IdentityError('unsupported entry request fields')
        path = Path(entry['project'])
        if path.is_absolute() or '..' in path.parts:
            raise IdentityError('entry must be workspace-relative')
        if entry['globalProperties'] != {'Configuration': 'Release', 'TargetFramework': 'net10.0'}:
            raise IdentityError('only Release/net10.0 global properties are qualified')
    if not entries: raise IdentityError('entry points required')
    state = Path(state).resolve()
    source = Path(source).resolve()
    if source == state or source.is_relative_to(state) or state.is_relative_to(source):
        raise IdentityError('source and owned state must be disjoint')
    if state == ROOT or state.is_relative_to(ROOT) or ROOT.is_relative_to(state):
        raise IdentityError('owned state must be disjoint from the controller checkout')
    state.mkdir(parents=True, exist_ok=True)
    # Keep the lease for the entire capture. RUL-6 must keep an equivalent lease
    # across revalidation and consumption; a matching JSON file is not a lease.
    with (state / 'lease').open('a') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        marker = state / 'owner.json'
        if not marker.exists():
            if any(p.name != 'lease' for p in state.iterdir()):
                raise IdentityError('state directory is not owned by discovery capture')
            marker.write_text(json.dumps({'policy': POLICY}))
        if json.loads(marker.read_text()) != {'policy': POLICY}:
            raise IdentityError('state owner policy mismatch')
        for name in ('workspace', 'output', 'tools'):
            if (state / name).exists(): shutil.rmtree(state / name)
        workspace, output = state / 'workspace', state / 'output'
        output.mkdir()
        seal(source, workspace)
        for name in ('home', 'tmp', 'http'): (output / name).mkdir()
        closure = subprocess.check_output(['/nix/var/nix/profiles/default/bin/nix-store', '-qR', str(SDK.parents[1])], text=True).splitlines()
        roots = {'workspace': workspace, **{f'runtime-{i}': Path(p) for i, p in enumerate(sorted(closure))}}
        for name in ('GraphExport', 'EvaluationProbe'):
            original = ROOT / 'tools' / name
            if not (original / 'bin/Release/net10.0' / (name + '.dll')).is_file():
                raise IdentityError('build tool before qualification: ' + name)
            roots[name] = state / 'tools' / name
            shutil.copytree(original, roots[name])
        profile = sandbox_profile([*roots.values(), output], output)
        profile_path = output / 'sandbox.sb'
        profile_path.write_text(profile)
        env = controlled_environment(output)
        invocation = dict(policy=POLICY, timestampEpoch=EPOCH, entries=entries,
                          sandboxSha256=digest(profile), contractSha256=CONTROLLER_DIGEST)
        host = dict(platform=platform.platform(), machine=platform.machine(),
                    osBuild=subprocess.check_output(['/usr/bin/sw_vers', '-buildVersion'], text=True).strip(),
                    bootSession=subprocess.check_output(['/usr/sbin/sysctl', '-n', 'kern.bootsessionuuid'], text=True).strip(),
                    cpuCount=os.cpu_count())
        before = capture(roots, request=invocation, environment=env, host=host, protected_store=protected_store)
        if candidate_adapter is not None:
            candidate = candidate_adapter(candidate, before, host)
            validate_certificate(candidate)
        if candidate is not None:
            unchanged = compare(candidate['identity'], before)['unchanged'] and not any(Path(path).exists() for path in candidate['externalAbsent'])
            result = dict(eligible=unchanged, unchanged=unchanged, reuseEnabled=False,
                          discoveryExecuted=False, identity=before, operation='GraphExport')
            if candidate_adapter is not None: result['candidateCertificate'] = candidate
            if not unchanged and candidate_graph is not None and not any(Path(path).exists() for path in candidate['externalAbsent']):
                from preparation_source_update import refresh
                refreshed = refresh(candidate, candidate_graph, before)
                if refreshed is not None:
                    graph, certificate = refreshed
                    (output / 'graph.json').write_text(json.dumps(graph, indent=2) + '\n')
                    result.update(eligible=True, sourceContentUpdate=True, certificate=certificate,
                                  changedSources=certificate['derivation']['changedSources'])
            (output / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
            yield result
            if not compare(before, capture(roots, request=invocation, environment=env, host=host, protected_store=protected_store))["unchanged"]:
                raise IdentityError("leased discovery inputs changed during consumption")
            # A stale negative observation already caused a miss. Only an
            # accepted candidate promises those paths remain absent during use.
            if result['eligible'] and any(Path(path).exists() for path in candidate["externalAbsent"]):
                raise IdentityError("external namespace changed during consumption")
            return

        def run(name, request):
            request_path = output / (name + '-request.json')
            request_path.write_text(json.dumps(request))
            result = subprocess.run(['/usr/bin/sandbox-exec', '-f', str(profile_path), str(SDK / 'dotnet'),
                str(roots[name] / 'bin/Release/net10.0' / (name + '.dll')), '--request', str(request_path)],
                cwd=workspace, env=env, capture_output=True, text=True, timeout=180)
            (output / (name + '.log')).write_text(result.stdout + result.stderr)
            if result.returncode:
                raise IdentityError('sandboxed discovery failed: ' + name + ': exit ' + str(result.returncode) + ': ' + result.stdout[-900:] + result.stderr[:1200] + result.stderr[-600:])

        targets = roots['GraphExport'] / 'Bazel.GraphExport.targets'
        graph_entries = [dict(project=e['project'], globalProperties=dict(e['globalProperties'],
            BazelGraphExport='true', CustomAfterMicrosoftCommonTargets=str(targets),
            RestorePackagesPath=str(workspace / '.nuget/packages'))) for e in entries]
        run('EvaluationProbe', dict(workspace=str(workspace), dotnetRoot=str(SDK), sdkVersion='10.0.400',
            entryPoints=graph_entries, properties=['ProjectAssetsFile'], items=[], mode='recorded', output=str(output / 'evaluation.json')))
        evidence = json.loads((output / 'evaluation.json').read_text())
        trusted_packages = set()
        for index, node in enumerate(evidence['rounds'][0]['nodes']):
            project = Path(node['project']).relative_to(workspace)
            assets = Path(node['values']['ProjectAssetsFile']).relative_to(workspace)
            try:
                _, libraries = graph_packages.package_plan(workspace, project, assets, 'net10.0')
            except (ValueError, KeyError) as error:
                raise IdentityError('invalid discovery restore inputs: ' + str(error)) from error
            if any(identity.lower() not in QUALIFIED_PACKAGES for identity in libraries):
                raise IdentityError('discovery package behavior is not qualified')
            verified = output / ('verified-' + str(index))
            try:
                manifest_path, _ = graph_packages.stage(workspace, project, verified, str(index), assets, 'net10.0')
            except (ValueError, KeyError) as error:
                raise IdentityError('invalid discovery package payload: ' + str(error)) from error
            for package in json.loads((verified / manifest_path).read_text())['packages']:
                folder = workspace / '.nuget/packages' / package['path']
                archive_paths = {f['path'] for f in package['files']}
                for path in folder.rglob('*'):
                    if path.is_file() and path.relative_to(folder).as_posix() not in archive_paths | {'.nupkg.metadata'}:
                        # NuGet omits archive bookkeeping, but extra executable
                        # files must not become an unqualified assembly closure.
                        raise IdentityError('unexpected package payload: ' + str(path))
                trusted_packages.update(folder / name for name in archive_paths if name in PACKAGE_IMPORTS)
                for name in archive_paths:
                    expected = TEST_PACKAGES['imports'].get(package['path'] + '/' + name)
                    if expected is not None:
                        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != expected:
                            raise IdentityError('test-package discovery import differs from reviewed bytes')
                        trusted_packages.add(folder / name)
        external_absent = set()
        for observation in evidence['rounds'][0]['observations']:
            path = Path(observation['path'])
            if path.is_relative_to(output):
                raise IdentityError('discovery consulted mutable scratch state: ' + str(path))
            if not any(path.is_relative_to(root) for root in roots.values()):
                # Outside-domain absence is enforced by the sandbox. Successful
                # external probes/enumerations are not silently accepted.
                if observation['operation'] not in {'exists', 'file-exists', 'directory-exists'} or observation['result'] != 'false':
                    raise IdentityError('unqualified external observation: ' + str(path))
                if path.exists():
                    raise IdentityError('sandbox hid an existing undeclared input: ' + str(path))
                external_absent.add(str(path))
        for node in evidence['rounds'][0]['nodes']:
            for item in node['imports']:
                path = Path(item['path'])
                if path.is_relative_to(workspace):
                    if path not in trusted_packages: check_xml(path)
                elif path != targets and SDK_IMPORTS.get(str(path)) != item['sha256']:
                    raise IdentityError('unqualified SDK/host import: ' + str(path))
        run('GraphExport', dict(schemaVersion=1, workspace=str(workspace), dotnetRoot=str(SDK), sdkVersion='10.0.400',
            packageRoot=str(workspace / '.nuget/packages'), entryPoints=entries, output=str(output / 'graph.json')))
        after = capture(roots, request=invocation, environment=env, host=host, protected_store=protected_store)
        if not compare(before, after)['unchanged']:
            raise IdentityError('discovery inputs changed during consumption')
        if any(Path(path).exists() for path in external_absent):
            raise IdentityError('external namespace changed during capture')
        if CONTROLLER_DIGEST != digest({name: (ROOT / 'tools' / name).read_text() for name in CONTROLLER_FILES}):
            raise IdentityError('discovery controller changed during capture')
        certificate = dict(schemaVersion=1, policy=POLICY, eligible=True, reuseEnabled=False,
                           operation='GraphExport', identity=before,
                           graphSha256=digest(json.loads((output / 'graph.json').read_text())),
                           observationSha256=digest(evidence), timestampEpoch=EPOCH,
                           externalAbsent=sorted(external_absent))
        certificate['sha256'] = digest(certificate)
        (output / 'certificate.json').write_text(json.dumps(certificate, indent=2) + '\n')
        yield certificate
        if not compare(before, capture(roots, request=invocation, environment=env, host=host, protected_store=protected_store))["unchanged"]:
            raise IdentityError("leased discovery inputs changed during consumption")
        if any(Path(path).exists() for path in external_absent):
            raise IdentityError("external namespace changed during consumption")


def qualify(source, state, entries, *, candidate=None):
    """Return qualification evidence; callers consuming inputs use qualified_view."""
    with qualified_view(source, state, entries, candidate=candidate) as result:
        return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--entries', type=Path, required=True)
    parser.add_argument('--candidate', type=Path)
    args = parser.parse_args()
    try:
        result = qualify(args.workspace, args.state, json.loads(args.entries.read_text()),
                         candidate=json.loads(args.candidate.read_text()) if args.candidate else None)
        print(json.dumps({key: result[key] for key in ('eligible', 'reuseEnabled', 'operation')}))
    except (IdentityError, OSError, ValueError) as error:
        print('discovery-ineligible: ' + str(error))
        raise SystemExit(2)
