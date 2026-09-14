"""Distinguish already-invalid candidates from mutations of an accepted lease."""
from contextlib import ExitStack, contextmanager
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import discovery_contract as discovery
import preparation_reuse as reuse
from preparation_identity import IdentityError


class CandidateLeaseTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.source = self.root / 'source'
        self.source.mkdir()
        self.external = self.root / 'optional.props'
        self.candidate = dict(identity={}, externalAbsent=[str(self.external)])
        self.entries = [dict(project='App.csproj', globalProperties=dict(Configuration='Release', TargetFramework='net10.0'))]
        # Only filesystem staging and host/identity acquisition are mocked. The
        # candidate decision, context lifetime and caller control flow are real.
        for target, options in (
            ('validate_certificate', {}), ('seal', {}), ('shutil.copytree', {}),
            ('capture', {'return_value': {}}), ('compare', {'return_value': {'unchanged': True}}),
            ('subprocess.check_output', {'return_value': ''}),
            ('subprocess.run', {'side_effect': AssertionError('unexpected discovery execution')}),
            ('platform.system', {'return_value': 'Darwin'}),
            ('platform.machine', {'return_value': 'arm64'}),
        ):
            self.stack.enter_context(patch('discovery_contract.' + target, **options))
        self.stack.enter_context(patch.object(discovery, 'SDK', self.source))
        self.stack.enter_context(patch.object(Path, 'is_file', return_value=True))

    def test_external_input_present_before_validation_returns_miss(self):
        self.external.write_text('<Project/>')
        result = discovery.qualify(self.source, self.root / 'state', self.entries, candidate=self.candidate)
        self.assertFalse(result['unchanged'])
        self.assertFalse(result['eligible'])
        self.assertFalse(result['discoveryExecuted'])

    def test_external_input_appearing_during_accepted_lease_rejects(self):
        with self.assertRaisesRegex(IdentityError, 'external namespace changed during consumption'):
            with discovery.qualified_view(self.source, self.root / 'state', self.entries, candidate=self.candidate) as result:
                self.assertTrue(result['unchanged'])
                self.external.write_text('<Project/>')

    def test_reuse_miss_reaches_fresh_preparation(self):
        self.external.write_text('<Project/>')
        real_view = discovery.qualified_view
        calls = []
        @contextmanager
        def view(*args, **kwargs):
            calls.append('validate' if kwargs.get('candidate') else 'capture')
            if not kwargs.get('candidate'):
                raise IdentityError('new external input is outside qualified read domain')
            with real_view(*args, **kwargs) as result:
                yield result
        @contextmanager
        def fresh(*args, **kwargs):
            calls.append('fresh')
            yield {'reused': False}
        with patch.object(reuse.prepare_graph, 'DOTNET_ROOT', self.source), \
             patch.object(reuse, 'tool_identity', return_value={}), \
             patch.object(reuse, 'read_candidate', return_value=((self.root / 'generation', {'certificate': self.candidate}), None)), \
             patch.object(discovery, 'qualified_view', side_effect=view), \
             patch.object(reuse, 'fresh_view', side_effect=fresh):
            with reuse.prepared_view(self.source, self.root / 'cache', self.root / 'out', self.entries) as result:
                self.assertFalse(result['reused'])
        self.assertEqual(calls, ['validate', 'capture', 'fresh'])


if __name__ == '__main__': unittest.main()
