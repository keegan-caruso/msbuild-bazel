"""Create a closed JIT consumer from declared sources and locked runtime products.

Copies no Bazel output base or project snapshots. Relocate the resulting workspace
to a fresh machine, stop the producer, and run runtime_jit.py --phase consumer.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil

from runtime_jit_prepare import PINNED

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('seed_report', type=Path)
    parser.add_argument('output', type=Path, help='new source-only consumer workspace')
    args = parser.parse_args()
    source, output = args.workspace.resolve(), args.output.resolve()
    assert not output.exists() and not output.is_relative_to(source)
    seed = json.loads(args.seed_report.read_text())
    products = source / 'source-products.tar.gz'
    assert hashlib.sha256(products.read_bytes()).hexdigest() == seed['sourceProductsSha256']
    for path, digest in PINNED.items():
        assert hashlib.sha256((source / path).read_bytes()).hexdigest() == digest, path
    wanted = {'jit_bootstrap_restore', 'jit_bootstrap', 'jit_targeting_pack', 'jit_assets',
              'jit_test_build', 'jit_host', 'jit_add1'}
    build = (source / 'BUILD.bazel').read_text()
    calls, files = {}, {'jit-bootstrap.json', 'jit-test.json', 'source-products.tar.gz'}
    for node in ast.walk(ast.parse(build)):
        if not isinstance(node, ast.Call):
            continue
        name = next((ast.literal_eval(k.value) for k in node.keywords if k.arg == 'name'), None)
        if name not in wanted:
            continue
        values = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
        calls[values['name']] = ast.get_source_segment(build, node)
        files.update(values.get('srcs', []))
        files.update(values.get('packages', []))
    assert calls.keys() == wanted
    output.mkdir(parents=True)
    for path in sorted(files):
        relative = Path(path)
        assert not relative.is_absolute() and '..' not in relative.parts, path
        original = source / relative
        assert original.resolve().is_relative_to(source) and original.is_file(), path
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
    sdk = json.loads((source / 'jit-test.json').read_text())['SdkVersion']
    (output / 'MODULE.bazel').write_text(
        'module(name="runtime_jit_consumer")\nbazel_dep(name="rules_msbuild",version="0.0.0")\n'
        'local_path_override(module_name="rules_msbuild",path=' + json.dumps(str(ROOT)) + ')\n'
        'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
        'dotnet.sdk(name="dotnet",version=' + json.dumps(sdk) + ')\n'
        'use_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
    declarations = [
        'load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph", "msbuild_graph_restore", "msbuild_graph_output", "msbuild_graph_runner", "msbuild_graph_test", "msbuild_layout", "msbuild_runtime")',
        'load(":runtime_jit_artifacts.bzl", "runtime_jit_products")',
        'msbuild_graph_runner(name="graph_runner")',
    ]
    for name, prefix in [('jit_refs', 'references'), ('jit_archived_host', 'core-root')]:
        declarations.append('runtime_jit_products(name=' + repr(name) + ',archive="source-products.tar.gz",sha256=' + repr(seed['sourceProductsSha256']) + ',prefix=' + repr(prefix) + ')')
    declarations += ['msbuild_layout(name="jit_core_root",paths={":jit_archived_host":"."})']
    declarations += [calls[name] for name in sorted(calls)]
    (output / 'BUILD.bazel').write_text('\n'.join(declarations) + '\n')
    shutil.copyfile(Path(__file__).with_name('runtime_jit_artifacts.bzl'), output / 'runtime_jit_artifacts.bzl')
    shutil.copyfile(args.seed_report, output / 'seed.json')
    (output / 'consumer.json').write_text(json.dumps(dict(sourceDigests=PINNED,
        sourceProductsSha256=seed['sourceProductsSha256'], copiedInputs=len(files),
        scope='declared JIT bootstrap, sources and runtime artifact; no local cache'), indent=2) + '\n')
    print(output, flush=True)


if __name__ == '__main__':
    main()
