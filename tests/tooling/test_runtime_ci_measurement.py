"""Do not report recovered test results as actual executions in CI measurements."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
import sys
import tempfile
import unittest
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'graph_build/upstream'))
from runtime_recovered_tests import edited_sources, test_cache_counts, require_http_cache
from runtime_ci_raw import clean_products
from runtime_ci_compare import compare


def result(remote=False, local=False, status='PASSED'):
    return dict(testResult=dict(status=status, cachedLocally=local, executionInfo=dict(cachedRemotely=remote)))


class CiMeasurement(unittest.TestCase):
    def test_cache_preflight_accepts_miss_and_rejects_outage(self):
        class Handler(BaseHTTPRequestHandler):
            status = 404

            def do_GET(self):
                self.send_response(self.status)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = 'http://127.0.0.1:' + str(server.server_port)
        try:
            require_http_cache(url)
            Handler.status = 503
            with self.assertRaisesRegex(RuntimeError, 'refusing a local fallback'):
                require_http_cache(url)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
        with self.assertRaisesRegex(RuntimeError, 'unreachable'):
            require_http_cache(url)

    def test_comparison_rejects_different_edits_products_or_test_work(self):
        common = dict(contractSha256='contract', editToken='same', sourceEdits={'Source.cs': 'edit'},
            signatures={'suite': 'cases'}, outcomes={'passed': 1}, files={'Output.dll': dict(sha256='bytes', mode=420)},
            executedTests=9, commandSeconds=10)
        raw = dict(common, case='body', restoreSeconds=0, buildSeconds=1, publicationSeconds=1, testSeconds=8, scope='test')
        graph = dict(common, case='body', remoteTestHits=0, localTestHits=0, buildSeconds=2, testCommandSeconds=8)
        graph['files'] = {'Output.dll': dict(sha256='bytes', mode=0o555)}
        self.assertEqual(compare(raw, graph)['compiledFiles'], 1)
        for key, value in [('sourceEdits', {'Source.cs': 'other'}), ('files', {}),
            ('files', {'Output.dll': dict(sha256='bytes', mode=0o444)}), ('localTestHits', 1)]:
            with self.assertRaises(AssertionError):
                compare(raw, dict(graph, **{key: value}))

    def test_mixed_results_keep_execution_and_recovery_separate(self):
        counts = test_cache_counts([result(), result(remote=True), result(local=True)], 'yes')
        self.assertEqual(counts, dict(executed=1, remote=1, local=1))

    def test_correctness_control_rejects_cached_results(self):
        for row in [result(remote=True), result(local=True)]:
            with self.assertRaises(AssertionError):
                test_cache_counts([row], 'no')

    def test_fresh_remote_recovery_rejects_local_or_executed_results(self):
        self.assertEqual(test_cache_counts([result(remote=True)], 'yes', True)['executed'], 0)
        for row in [result(), result(local=True), result(remote=True, status='FAILED')]:
            with self.assertRaises(AssertionError):
                test_cache_counts([row], 'yes', True)

    def test_shared_edit_changes_both_api_sources_but_only_body_implementation(self):
        mutation = dict(implementation='Implementation.cs', reference='Reference.cs',
            bodyAnchor='return 1;', implementationAnchor='class C {', referenceAnchor='class C {')
        originals = {'Implementation.cs': b'class C { int F() { return 1; } }', 'Reference.cs': b'class C { }'}
        self.assertEqual(set(edited_sources(originals, mutation, 'body', 'same-token')), {'Implementation.cs'})
        api = edited_sources(originals, mutation, 'api', 'same-token')
        for source in originals:
            self.assertNotEqual(api[source], originals[source])
        self.assertEqual(api, edited_sources(originals, mutation, 'api', 'same-token'))
        self.assertNotEqual(api, edited_sources(originals, mutation, 'api', 'other-token'))

    def test_cold_cleanup_retains_inputs_packages_and_raw_driver(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ['src/Code.cs', '.nuget/keep', '.qualification/Raw.dll', 'artifacts/obj/old', 'artifacts/bin/Extra.dll', 'artifacts/restore/project.assets.json']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            node = dict(Inputs=['src/Code.cs'], OutputDirectories=['artifacts/obj'], OutputFiles=['artifacts/bin/Extra.dll'])
            contract = dict(SharedInputs=[], Restore=dict(Inputs=[], Outputs=['artifacts/restore/project.assets.json']), Projects={'P': dict(Inputs=[], Configurations=[node])})
            for bad in ['src', '.nuget', '../outside']:
                node['OutputDirectories'].append(bad)
                with self.assertRaises(AssertionError):
                    clean_products(root, contract)
                self.assertTrue((root / 'artifacts/obj/old').exists())
                node['OutputDirectories'].pop()
            clean_products(root, contract)
            self.assertFalse((root / 'artifacts/obj').exists())
            self.assertFalse((root / 'artifacts/bin/Extra.dll').exists())
            self.assertFalse((root / 'artifacts/restore/project.assets.json').exists())
            for name in ['src/Code.cs', '.nuget/keep', '.qualification/Raw.dll']:
                self.assertEqual((root / name).read_text(), name)


if __name__ == '__main__':
    unittest.main()
