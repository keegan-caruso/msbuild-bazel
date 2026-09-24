"""Qualify declared layout expansion, sandbox execution and cache recovery."""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('directory', type=Path)
p.add_argument('--remote-cache')
a = p.parse_args()
a.directory.mkdir(parents=True)
workspace = a.directory.resolve() / 'source'
workspace.mkdir()
sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
bazel = os.environ['RULES_MSBUILD_BAZEL']
version = subprocess.check_output([bazel, '--version'], text=True).strip()
assert version == 'bazel ' + os.environ['USE_BAZEL_VERSION'], version

def put(name, text):
    (workspace / name).write_text(text)

put('MODULE.bazel', f'''module(name="layout_sandbox")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(str(sdk))},include_runtime_closure=False)
register_toolchains("//:registered")
''')
put('trees.bzl', '''def _tree(ctx):
    tree = ctx.actions.declare_directory(ctx.label.name)
    ctx.actions.run_shell(
        inputs = [ctx.file.src], outputs = [tree],
        arguments = [tree.path, ctx.file.src.path],
        command = "mkdir -p \\\"$1/nested space\\\"; cp \\\"$2\\\" \\\"$1/nested space/value.txt\\\"; printf '#!/bin/sh\\\\nexit 0\\\\n' > \\\"$1/host\\\"; chmod 755 \\\"$1/host\\\"",
    )
    return [DefaultInfo(files = depset([tree]))]
tree = rule(implementation = _tree, attrs = {"src": attr.label(allow_single_file = True)})
def _empty(ctx):
    tree = ctx.actions.declare_directory(ctx.label.name)
    ctx.actions.run_shell(outputs = [tree], arguments = [tree.path], command = 'mkdir -p "$1"')
    return [DefaultInfo(files = depset([tree]))]
empty = rule(implementation = _empty)
''')
header = '''load("@rules_msbuild//msbuild:toolchain.bzl", "msbuild_toolchain")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_layout")
load(":trees.bzl", "tree", "empty")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
tree(name="generated", src="value.txt")
empty(name="empty")
msbuild_layout(name="first", paths={":generated": ".", ":empty": "empty", "alias.txt": "file with spaces.txt"})
msbuild_layout(name="nested", paths={":first": "runtime"})
msbuild_layout(name="empty_layout", paths={})
'''
put('BUILD.bazel', header)
put('value.txt', 'first\n')
(workspace / 'alias.txt').symlink_to('value.txt')
cache = ['--remote_cache=' + a.remote_cache, '--disk_cache='] if a.remote_cache else ['--disk_cache=' + str(a.directory.resolve() / 'cache')]
records = []

def run(name, base='producer', target=':nested', error=None, recovered=False):
    log = a.directory.resolve() / (name + '.json')
    command = [bazel, '--output_base=' + str(a.directory.resolve() / base), 'build', target,
               '--spawn_strategy=sandboxed', '--strategy=MSBuildLayout=sandboxed',
               '--execution_log_json_file=' + str(log), '--remote_download_outputs=all',
               '--lockfile_mode=off', '--jobs=2',
               '--remote_accept_cached=' + str(recovered).lower(), *cache]
    result = subprocess.run(command, cwd=workspace, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (a.directory / (name + '.log')).write_text(result.stdout)
    if error:
        assert result.returncode != 0 and error in result.stdout, result.stdout
        records.append({'case': name, 'rejected': True})
        return
    assert result.returncode == 0, result.stdout
    decoder = json.JSONDecoder()
    text = log.read_text().strip()
    actions = []
    while text:
        row, end = decoder.raw_decode(text)
        actions.append(row)
        text = text[end:].lstrip()
    layouts = [row for row in actions if row.get('mnemonic') == 'MSBuildLayout']
    summary = [(row.get('targetLabel'), row.get('runner'), row.get('cacheHit')) for row in layouts]
    assert layouts, name
    if recovered:
        assert all(row.get('cacheHit') for row in layouts), summary
    else:
        runner = 'linux-sandbox' if sys.platform == 'linux' else 'darwin-sandbox'
        assert all(row.get('runner') == runner for row in layouts), summary
    records.append({'case': name, 'layouts': len(layouts), 'recovered': recovered})

def verify(value):
    root = workspace / 'bazel-bin/nested.layout/runtime'
    assert (root / 'nested space/value.txt').read_text() == value
    assert (root / 'file with spaces.txt').read_text() == value
    assert (root / 'host').stat().st_mode & stat.S_IXUSR
    assert not any(path.is_symlink() for path in root.rglob('*'))
    assert subprocess.run([str(root / 'host')]).returncode == 0

run('cold')
verify('first\n')
# Bazel does not preserve empty subdirectories inside tree artifacts, but an
# explicitly selected empty tree must still produce a valid layout root.
run('empty', target=':empty_layout')
assert (workspace / 'bazel-bin/empty_layout.layout').is_dir()
run('recovery', base='consumer', recovered=True)
verify('first\n')
put('value.txt', 'changed\n')
run('mutation')
verify('changed\n')
put('collision.txt', 'conflict\n')
put('BUILD.bazel', header + 'msbuild_layout(name="collision", paths={":generated": ".", "collision.txt": "nested space/value.txt"})\n')
run('collision', target=':collision', error='Conflicting runtime/input destination')
put('BUILD.bazel', header + 'msbuild_layout(name="escape", paths={":generated": "../outside"})\n')
run('escape', target=':escape', error='Unsafe logical path')
(a.directory / 'results.json').write_text(json.dumps(records, indent=2) + '\n')
print(version)
print(json.dumps(records, indent=2))
for base in ('producer', 'consumer'):
    subprocess.run([bazel, '--output_base=' + str(a.directory.resolve() / base), 'shutdown'], cwd=workspace, check=True)
