#!/usr/bin/env python3
"""R05 source-built generator/reference-role acceptance against ordinary MSBuild."""
import argparse
from contextlib import nullcontext
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess

from bazel_session import BazelSession
from prepare_graph import ROOT, DOTNET_ROOT, prepare
from probe_graph_execution import BAZEL
from probe_graph_cache import cache_environment
from probe_bazel import json_stream

FIXTURE = ROOT / 'tests/fixtures/generator-roles'
PROJECT = 'App/App.csproj'
ASSEMBLY = 'App/bin/Release/net10.0/App.dll'
PROJECTS = {'App', 'Shared', 'ClassicGenerator', 'IncrementalGenerator', 'OrderOnly'}


def edit(path, old, new):
    contents = path.read_text()
    if contents.count(old) != 1:
        raise AssertionError('mutation requires one matching declaration: ' + str(path))
    path.write_text(contents.replace(old, new))


def mutate(source, case):
    if case == 'consumer':
        with (source / 'App/Program.cs').open('a') as stream:
            stream.write('Console.WriteLine("consumer-v2");\n')
    elif case == 'generatorFailure':
        edit(source / 'ClassicGenerator/ClassicValueGenerator.cs', 'var values = new List<string>();',
             'throw new InvalidOperationException("R05 deliberate generator failure");\n        var values = new List<string>();')
        edit(source / PROJECT, '<OutputType>Exe</OutputType>',
             '<OutputType>Exe</OutputType><WarningsAsErrors>CS8785</WarningsAsErrors>')
    elif case == 'classic':
        edit(source / 'ClassicGenerator/ClassicValueGenerator.cs',
            'out var prefix);', 'out var prefix);\n        prefix += "-classic-v2";')
    elif case == 'incremental':
        edit(source / 'IncrementalGenerator/IncrementalValueGenerator.cs',
            '? value\n', '? value + "-incremental-v2"\n')
    elif case == 'additional':
        (source / 'App/values/alpha.txt').write_text('two\n')
        (source / 'App/values/beta.txt').write_text('added\n')
    elif case == 'removed':
        (source / 'App/values/alpha.txt').unlink()
        (source / 'App/values/sentinel.txt').unlink()
    elif case == 'property':
        edit(source / PROJECT, '<GeneratorPrefix>fixture-v1</GeneratorPrefix>',
             '<GeneratorPrefix>fixture-v2</GeneratorPrefix>')
    elif case == 'editorconfig':
        edit(source / 'App/.editorconfig', 'editor-v1', 'editor-v2')
    elif case in ('suppressed', 'severityError'):
        path = source / 'App/.editorconfig'
        contents = path.read_text()
        if contents.count('severity = warning') != 2:
            raise AssertionError('both generator diagnostic settings required')
        path.write_text(contents.replace('severity = warning',
            'severity = ' + ('none' if case == 'suppressed' else 'error')))
    elif case == 'warningsAsErrors':
        edit(source / PROJECT, '<OutputType>Exe</OutputType>',
             '<OutputType>Exe</OutputType><TreatWarningsAsErrors>true</TreatWarningsAsErrors>')
    elif case == 'orderOnly':
        edit(source / 'OrderOnly/OrderOnly.csproj', 'order-only-v1', 'order-only-v2')
        edit(source / 'OrderOnly/Marker.cs', 'order-only-v1', 'order-only-v2')
    else:
        raise ValueError('unknown mutation: ' + case)


def inventory(folder):
    return {path.relative_to(folder).as_posix(): dict(
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        executable=bool(path.stat().st_mode & 0o111))
        for path in sorted(folder.rglob('*')) if path.is_file()}


def remove_tree(folder):
    if not folder.exists():
        return
    for directory, _, _ in os.walk(folder, followlinks=False):
        path = Path(directory)
        if not path.is_symlink():
            path.chmod(path.stat().st_mode | 0o700)
    shutil.rmtree(folder)


class Probe:
    projects = PROJECTS
    failure_diagnostics = ['GEN001', 'GEN002']
    def __init__(self, output):
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.source = self.output / 'preparation'
        self.generated = self.output / 'generated'
        self.base = self.output / 'bazel-base'
        self.session = None
        self.strategy = 'darwin-sandbox' if platform.system() == 'Darwin' else 'linux-sandbox'
        self.report = dict(schemaVersion=1, accepted=False, scope='R05-package-free-project-generator-roles',
            platform=platform.platform(), sdkVersion='10.0.400', bazelVersion='8.4.2',
            configuration='Release', targetFramework='net10.0', cases={})

    def save(self):
        (self.output / 'report.json').write_text(json.dumps(self.report, indent=2) + '\n')

    def run(self, name, args, cwd, success=True):
        env = cache_environment(self.output, cwd)
        if str(args[0]) == str(BAZEL):
            args = self.session.prepare(args, cwd, env)
        uses_shared_tools = any(str(argument).startswith(str(ROOT / 'tools') + '/') for argument in args)
        lock = ROOT / 'artifacts/graph-preparation.lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open('a') if uses_shared_tools else nullcontext() as handle:
            if handle is not None:
                fcntl.flock(handle, fcntl.LOCK_EX)
            result = subprocess.run(list(map(str, args)), cwd=cwd, env=env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
        (self.output / (name + '.log')).write_text(result.stdout)
        if success and result.returncode:
            raise RuntimeError(name + ' failed:\n' + result.stdout[-14000:])
        return result

    def copy(self, destination):
        shutil.copytree(FIXTURE, destination)
        (destination / '.nuget/packages').mkdir(parents=True)

    def restore(self, source, name):
        self.run(name + '-restore', [DOTNET_ROOT / 'dotnet', 'msbuild', PROJECT, '-t:Restore',
            '-p:Configuration=Release', '-nodeReuse:false', '-nologo'], source)

    def export(self, source, name, success=True):
        request = self.output / (name + '-request.json')
        manifest = self.output / (name + '-manifest.json')
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(source),
            dotnetRoot=str(DOTNET_ROOT), sdkVersion='10.0.400', packageRoot=str(source / '.nuget/packages'),
            entryPoints=[dict(project=PROJECT, globalProperties={'Configuration': 'Release'})], output=str(manifest))))
        result = self.run(name + '-export', [DOTNET_ROOT / 'dotnet',
            ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], source, success)
        return manifest, result

    def generate(self, name, mutation=None):
        if self.source.exists():
            remove_tree(self.source)
        self.copy(self.source)
        if mutation:
            mutation(self.source)
        self.restore(self.source, name)
        manifest, _ = self.export(self.source, name)
        if list(self.source.glob('*/bin/**/*.dll')):
            raise AssertionError('preparation compiled a project')
        if self.generated.exists():
            remove_tree(self.generated)
        graph = prepare(self.source, manifest, self.generated,
            environment=cache_environment(self.output, self.source))
        self.run(name + '-starlark', ['python3', ROOT / 'scripts/check-starlark.py', '--workspace', self.generated], ROOT)
        by_name = {Path(node['project']).stem: node for node in graph['nodes']}
        if set(by_name) != self.projects:
            raise AssertionError('unexpected project graph')
        if set(by_name['App']['dependencies']) != {node['id'] for key, node in by_name.items() if key != 'App'}:
            raise AssertionError('all compile/analyzer/build-order producers must be direct scheduling edges')
        if any(node['dependencies'] for key, node in by_name.items() if key != 'App'):
            raise AssertionError('unexpected producer dependency')
        self.graph = graph
        self.nodes = by_name
        remove_tree(self.source)
        return graph

    def ordinary(self, name, mutation=None, fail=False):
        source = self.output / ('ordinary-' + name)
        self.copy(source)
        if mutation:
            mutation(source)
        self.restore(source, 'ordinary-' + name)
        result = self.run('ordinary-' + name + '-build', [DOTNET_ROOT / 'dotnet', 'msbuild', PROJECT,
            '-t:Build', '-p:Configuration=Release', '-nodeReuse:false', '-nologo', '-verbosity:normal'], source, not fail)
        if fail:
            if result.returncode == 0 or any('error ' + code not in result.stdout for code in self.failure_diagnostics):
                raise AssertionError('ordinary warning-as-error control did not reject both generators')
            return dict(returncode=result.returncode, diagnostics=self.failure_diagnostics)
        runtime = self.run('ordinary-' + name + '-app', [DOTNET_ROOT / 'dotnet', source / ASSEMBLY], source)
        return dict(output=runtime.stdout.strip(), roles=self.roles(result.stdout),
            diagnostics=sorted(set(re.findall(r'warning (GEN00[12])', result.stdout))),
            runtimeFiles=sorted(path.name for path in (source / ASSEMBLY).parent.glob('*.dll')))

    @staticmethod
    def roles(log):
        def paths(option):
            return sorted(set(first or second for first, second in re.findall(
                r'(?:^|\s)/' + option + r':(?:"([^"]+)"|(\S+))', log)))
        if 'CompilerServer: tool - using command line tool by design' not in log:
            raise AssertionError('fixture must execute a fresh compiler process')
        analyzers = paths('analyzer')
        references = paths('reference')
        # Normal logs include producer compiler commands too. The generator
        # outputs must occur only in analyzer arguments, never as /reference.
        for name in ('ClassicGenerator', 'IncrementalGenerator'):
            if not any(path.endswith('/' + name + '/bin/Release/net10.0/' + name + '.dll') for path in analyzers):
                raise AssertionError('generator implementation missing from analyzer inputs: ' + name)
        forbidden = ('ClassicGenerator.dll', 'IncrementalGenerator.dll', 'OrderOnly.dll')
        if any(path.endswith(forbidden) for path in references):
            raise AssertionError('non-reference producer leaked into compiler references')
        if not any(path.endswith('/Shared.dll') for path in references):
            raise AssertionError('ordinary library missing from compiler references')
        return dict(projectAnalyzers=[Path(path).name for path in analyzers if Path(path).stem in PROJECTS],
            ordinaryReference='Shared.dll', excludedReferences=list(forbidden))

    def build(self, name, expected, baseline, fail=False):
        execution = self.output / (name + '-execution.json')
        targets = ['//:node_' + node['id'] for node in self.graph['nodes']]
        result = self.run(name + '-bazel', [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc',
            '--output_base=' + str(self.base), '--output_user_root=' + str(self.output / 'bazel-user'),
            'build', *targets, '--disk_cache=' + str(self.output / 'disk-cache'),
            '--spawn_strategy=' + self.strategy, '--strategy=MsbuildProject=' + self.strategy,
            '--jobs=2', '--noshow_progress', '--color=no', '--curses=no', '--remote_download_outputs=all',
            '--execution_log_json_file=' + str(execution)], self.generated, not fail)
        actions = []
        evidence = self.output / 'evidence' / name
        evidence.mkdir(parents=True)
        for record in json_stream(execution):
            if record.get('mnemonic') != 'MsbuildProject':
                continue
            identity = record['targetLabel'].split(':node_')[-1]
            project = next(Path(node['project']).stem for node in self.graph['nodes'] if node['id'] == identity)
            action = dict(project=project, cacheHit=record.get('cacheHit', False), runner=record.get('runner'))
            diagnostics = self.generated / ('bazel-bin/node_' + identity + '.diagnostics')
            if diagnostics.is_dir():
                shutil.copytree(diagnostics, evidence / project)
                detail = json.loads((diagnostics / 'action.json').read_text())
                action['compiledProjects'] = detail['compiledProjects']
                if not action['cacheHit'] and detail['compiledProjects'] != [project]:
                    raise AssertionError('dependency compilation repeated inside ' + project)
            if not action['cacheHit'] and action['runner'] != self.strategy:
                raise AssertionError('native sandbox required')
            actions.append(action)
        executed = sorted(action['project'] for action in actions if not action['cacheHit'])
        if executed != sorted(expected):
            raise AssertionError(name + ' unexpected executed projects: ' + str(executed))
        item = dict(actions=actions, executionLog=execution.name, baseline=baseline,
            preparationWorkspaceAbsent=not self.source.exists(), returncode=result.returncode)
        self.report['cases'][name] = item
        self.save()
        if fail:
            if result.returncode == 0 or any('error ' + code not in result.stdout for code in self.failure_diagnostics):
                raise AssertionError('adapter warning-as-error control did not reject both generators')
            app_bundle = self.generated / ('bazel-bin/node_' + self.nodes['App']['id'] + '.bundle')
            if (app_bundle / 'bundle.json').exists():
                raise AssertionError('failed diagnostic action published a successful App bundle')
            item['diagnostics'] = self.failure_diagnostics
            self.save()
            return item
        bundles = {}
        for project, node in self.nodes.items():
            bundle = self.generated / ('bazel-bin/node_' + node['id'] + '.bundle')
            if not bundle.is_dir():
                raise AssertionError('missing project bundle: ' + project)
            bundles[project] = inventory(bundle)
        app_bundle = self.generated / ('bazel-bin/node_' + self.nodes['App']['id'] + '.bundle')
        runtime = self.run(name + '-app', [DOTNET_ROOT / 'dotnet', app_bundle / 'artifacts' / ASSEMBLY], self.generated)
        if runtime.stdout.strip() != baseline['output']:
            raise AssertionError('ordinary/generated API behavior differs')
        runtime_files = sorted(path.name for path in (app_bundle / 'artifacts' / ASSEMBLY).parent.glob('*.dll'))
        if runtime_files != baseline['runtimeFiles'] or runtime_files != ['App.dll', 'Shared.dll']:
            raise AssertionError('generator/build-order compiler dependencies leaked into app runtime')
        if 'App' in executed:
            roles = self.roles((evidence / 'App/build.log').read_text())
            if roles != baseline['roles']:
                raise AssertionError('ordinary/adapter reference roles differ')
            item['roles'] = roles
            diagnostics = sorted(set(re.findall(r'warning (GEN00[12])', (evidence / 'App/build.log').read_text())))
            if diagnostics != baseline['diagnostics']:
                raise AssertionError('ordinary/adapter generator diagnostics differ')
            item['diagnostics'] = diagnostics
        item.update(output=runtime.stdout.strip(), runtimeFiles=runtime_files, bundleFiles=bundles)
        self.save()
        return item

    def execute(self, cold_only=False):
        self.report['caseSelection'] = 'cold-only' if cold_only else 'full'
        stage = 'exporter bootstrap'
        try:
            self.run('exporter-build', [DOTNET_ROOT / 'dotnet', 'build', ROOT / 'tools/GraphExport', '-c', 'Release', '--nologo'], ROOT)
            stage = 'ordinary baseline'
            baseline = self.ordinary('cold')
            with BazelSession(self.output) as self.session:
                stage = 'cold'
                self.generate('cold')
                cold = self.build('cold', self.projects, baseline)
                if not cold_only:
                    stage = 'unchanged'
                    self.generate('unchanged')
                    self.build('unchanged', [], baseline)
                    for case in ('classic', 'incremental', 'additional', 'removed', 'property',
                                 'editorconfig', 'suppressed', 'severityError', 'warningsAsErrors', 'orderOnly', 'generatorFailure'):
                        stage = case
                        mutation = lambda source, selected=case: mutate(source, selected)
                        fail = case in ('severityError', 'warningsAsErrors', 'generatorFailure')
                        self.failure_diagnostics = ['CS8785'] if case == 'generatorFailure' else ['GEN001', 'GEN002']
                        ordinary = self.ordinary(case, mutation, fail)
                        if not fail:
                            unchanged = case in ('suppressed', 'orderOnly')
                            if (ordinary['output'] == baseline['output']) != unchanged:
                                raise AssertionError('mutation ordinary observable effect differs: ' + case)
                            expected_diagnostics = [] if case in ('removed', 'suppressed') else ['GEN001', 'GEN002']
                            if ordinary['diagnostics'] != expected_diagnostics:
                                raise AssertionError('ordinary diagnostic behavior differs: ' + case)
                        self.generate(case, mutation)
                        producers = {'classic': ['ClassicGenerator'], 'incremental': ['IncrementalGenerator'],
                                     'orderOnly': ['OrderOnly'], 'generatorFailure': ['ClassicGenerator']}.get(case, [])
                        record = self.build(case, ['App', *producers], ordinary, fail)
                        if case == 'orderOnly':
                            state = 'artifacts/OrderOnly/bin/Release/net10.0/order-only.state'
                            if record['bundleFiles']['OrderOnly'][state] == cold['bundleFiles']['OrderOnly'][state]:
                                raise AssertionError('build-order producer state did not change')
            if not cold_only:
                stage = 'relocated'
                remove_tree(self.generated)
                remove_tree(self.base)
                old_base = self.base
                self.base = self.output / 'relocated-base'
                self.source = self.output / 'relocated-preparation'
                self.generated = self.output / 'relocated-generated'
                with BazelSession(self.output) as self.session:
                    self.generate('relocated')
                    absent_before = not old_base.exists() and not (self.output / 'generated').exists() and not self.source.exists()
                    if not absent_before:
                        raise AssertionError('producer state survived before recovery')
                    recovered = self.build('relocated', [], baseline)
                    if old_base.exists() or (self.output / 'generated').exists() or self.source.exists():
                        raise AssertionError('producer state survived recovery')
                    if recovered['bundleFiles'] != cold['bundleFiles']:
                        raise AssertionError('recovered bundle bytes or modes differ')
                    if sorted(action['project'] for action in recovered['actions'] if action['cacheHit'] and action['runner'] == 'disk cache hit') != sorted(self.projects):
                        raise AssertionError('five explicit disk-cache recoveries required')
                    recovered['producerStateAbsentBeforeBuild'] = True
                    stage = 'recoveredConsumer'
                    mutation = lambda source: mutate(source, 'consumer')
                    ordinary = self.ordinary('recoveredConsumer', mutation)
                    self.generate('recoveredConsumer', mutation)
                    self.build('recoveredConsumer', ['App'], ordinary)
            self.report['accepted'] = True
        except BaseException as error:
            self.report['failure'] = dict(stage=stage, type=type(error).__name__, message=str(error))
            raise
        finally:
            self.save()
        return self.report


def probe(output, cold_only=False):
    return Probe(output).execute(cold_only)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cold-only', action='store_true')
    args = parser.parse_args()
    probe(args.output, args.cold_only)
