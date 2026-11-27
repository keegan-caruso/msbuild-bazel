"""Public Bazel Blazor WebAssembly Build and real Chromium managed events.

Usage: python3 tests/graph_build/blazor_wasm.py FRESH_OUTPUT --browser CHROME
Requires the pinned Bazelisk bootstrap, network acquisition, Node 22+ (built-in
WebSocket), and a Chromium executable. Uses no installed WASM workload or host
SDK. Keeps logs/reports in FRESH_OUTPUT and shuts down its own Bazel server.
"""
import argparse
import functools
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import threading

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/fixtures/blazor-wasm'


def stage_assets(workspace, site):
    """Materialize the SDK's Build manifest using only the staged graph tree.

    Build assets span obj, wwwroot and restored packages. Original sandbox root
    prefixes in the SDK manifest are mapped to the retained graph workspace.
    This is a bounded fixture server, not a product deployment/export API.
    """
    manifest = json.loads((workspace / 'App/bin/Release/net11.0/App.staticwebassets.runtime.json').read_text())
    roots = manifest['ContentRoots']
    authored = [root for root in roots if root.endswith('/App/wwwroot/')]
    assert len(authored) == 1, roots
    original = authored[0][:-len('App/wwwroot/')]
    site.mkdir()
    # dotnet.js is generated in the physical Build wwwroot in SDK 11.
    shutil.copytree(workspace / 'App/bin/Release/net11.0/wwwroot', site, dirs_exist_ok=True,
                    copy_function=shutil.copyfile)
    for directory in [site] + [path for path in site.rglob("*") if path.is_dir()]:
        directory.chmod(directory.stat().st_mode | stat.S_IWUSR)

    def safe(relative):
        path = Path(relative)
        assert not path.is_absolute() and '..' not in path.parts, relative
        return path

    def visit(node, relative=Path()):
        asset = node.get('Asset')
        if asset:
            content_root = roots[asset['ContentRootIndex']]
            assert content_root.startswith(original), content_root
            source = workspace / safe(content_root[len(original):]) / safe(asset['SubPath'])
            source.resolve().relative_to(workspace.resolve())
            assert source.is_file(), source
            target = site / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        for name, child in (node.get('Children') or {}).items():
            visit(child, relative / safe(name))
    visit(manifest['Root'])


class AssetServer(ThreadingHTTPServer):
    # The runtime fetches many framework assets concurrently. A five-connection
    # Python 3.9 default backlog can reset valid requests during startup.
    request_queue_size = 128


class QuietHandler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    extensions_map = dict(SimpleHTTPRequestHandler.extensions_map, **{'.wasm': 'application/wasm', '.pdb': 'application/octet-stream'})

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--browser', required=True, type=Path)
    parser.add_argument('--node', default='node')
    args = parser.parse_args()
    base = args.directory.resolve()
    base.mkdir(parents=True, exist_ok=False)
    workspace = base / 'workspace'
    shutil.copytree(FIXTURE, workspace)
    module = workspace / 'MODULE.bazel'
    module.write_text(module.read_text().replace('RULES_PATH', str(ROOT)))
    env = dict(os.environ)
    for key in list(env):
        if key.startswith('RULES_MSBUILD_PROJECT_CACHE_'):
            env.pop(key)
    startup = [str(ROOT / 'scripts/bazel-launcher.sh'), '--ignore_all_rc_files', f'--output_base={base / "bazel"}']

    def bazel(name, *arguments):
        with (base / (name + '.log')).open('w') as log:
            result = subprocess.run(startup + list(arguments), cwd=workspace, env=env, stdout=log, stderr=subprocess.STDOUT)
        assert result.returncode == 0, f'{name} failed: {base / (name + ".log")}'

    results = []
    try:
        bazel('sync', 'run', '//:sync', '--jobs=2', '--remote_cache=', '--disk_cache=')
        bazel('sync-check', 'run', '//:sync', '--jobs=2', '--', '--check')
        build = workspace / 'BUILD.bazel'
        build.write_text(build.read_text() + '\nload(":graph.generated.bzl", "app_graph")\napp_graph(name="build", profile_build=True)\n')
        original_dll = None
        for label in ['wasm-v1', 'wasm-v2']:
            if label == 'wasm-v2':
                source = workspace / 'App/Counter.razor'
                source.write_text(source.read_text().replace('wasm-v1', 'wasm-v2'))
            bazel(label, 'build', '//:build', '--jobs=2', '--remote_cache=', '--disk_cache=',
                  f'--execution_log_json_file={base / (label + "-execution.json")}')
            graph = workspace / 'bazel-bin/build.graph'
            report = json.loads((graph / 'report.json').read_text())
            assert (report['hits'], report['misses'], report['compilerTasks']) == (0, 1, 1), report
            (base / (label + '-graph.json')).write_text(json.dumps(report, indent=2) + '\n')
            staged = graph / 'workspace'
            dll = hashlib.sha256((staged / 'App/bin/Release/net11.0/App.dll').read_bytes()).hexdigest()
            if original_dll is not None:
                assert dll != original_dll, 'Razor edit did not change managed bytes'
            original_dll = dll
            site = base / (label + '-site')
            stage_assets(staged, site)
            server = AssetServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(site)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with (base / (label + '-browser.json')).open('w') as output, (base / (label + '-browser.log')).open('w') as log:
                    result = subprocess.run([args.node, str(ROOT / 'tests/graph_build/wasm_browser.mjs'),
                        str(args.browser), f'http://127.0.0.1:{server.server_port}/', label],
                        stdout=output, stderr=log, timeout=90)
                assert result.returncode == 0, f'{label} browser failed: {base / (label + "-browser.log")}'
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
            browser = json.loads((base / (label + '-browser.json')).read_text())
            results.append(dict(revision=label, dllSha256=dll, hits=report['hits'], misses=report['misses'],
                compilerTasks=report['compilerTasks'], browser=browser['browser'], architecture=browser['architecture'],
                managedCount=browser['managedCount'], wasmResponses=sum(row['url'].endswith('.wasm') for row in browser['requests'])))
            print(f"PASS: {label}, graph compile, Wasm architecture, two managed browser clicks", flush=True)
        bazel('edited-sync-check', 'run', '//:sync', '--jobs=2', '--', '--check')
        (base / 'summary.json').write_text(json.dumps(dict(sdk='11.0.100', bazel=env.get('USE_BAZEL_VERSION') or (ROOT / '.bazelversion').read_text().strip(),
            packages=len(json.loads((workspace / 'nuget.lock.json').read_text())['packages']), runs=results), indent=2) + '\n')
    finally:
        bazel('shutdown', 'shutdown')


if __name__ == '__main__':
    main()
