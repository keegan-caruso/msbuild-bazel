"""Authored workspace snapshot for the managed runtime/JIT sync fixtures.

Compilation products are bound separately. Keep locks and implicit MSBuild inputs;
exclude Bazel control files and fixture reports so publication cannot key itself.
"""
import json

SYNC_SRCS = 'srcs=glob(["**"],exclude=' + repr([
    'BUILD.bazel', 'MODULE.bazel', 'MODULE.bazel.lock', 'graph.generated.json', 'graph.generated.bzl',
    '.git/**', '.tools/**', '.cache/**', '.nuget/**', '.package-source/**', '.cli/**',
    'bazel-*/**', '**/bin/**', '**/obj/**', 'artifacts/**',
    'jit-public.json', 'source-products.tar.gz',
]) + ',allow_empty=False)'


def action_records(path):
    text = path.read_text()
    decoder = json.JSONDecoder()
    while text.strip():
        row, end = decoder.raw_decode(text.lstrip())
        yield row
        text = text.lstrip()[end:]


def assert_preparation_reused(path):
    assert not any(row.get('mnemonic') == 'MSBuildSyncPrepare' for row in action_records(path)), 'Unchanged sync/check repeated qualification'
