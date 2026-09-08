"""Fail-closed acceptance checks, independent of SDK/package prerequisites."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from probe_spectre_acceptance import ANSI, CONSOLE, GENERATOR, PROJECTS, SPINNERS, mutate, verify_actions


class AcceptanceContractTests(unittest.TestCase):
    def action(self, name, cache=False, runner='darwin-sandbox', compiled=None):
        return dict(project=name, cacheHit=cache, runner=runner,
                    compiledProjects=[name] if compiled is None else compiled)

    def test_exact_workset_rejects_repeated_dependency(self):
        with self.assertRaises(AssertionError):
            verify_actions([self.action(CONSOLE, compiled=[CONSOLE, GENERATOR])], {CONSOLE}, 'darwin-sandbox')

    def test_exact_workset_rejects_extra_producer(self):
        with self.assertRaises(AssertionError):
            verify_actions([self.action(CONSOLE), self.action(ANSI)], {CONSOLE}, 'darwin-sandbox')

    def test_exact_workset_rejects_missing_consumer(self):
        with self.assertRaises(AssertionError):
            verify_actions([], {CONSOLE}, 'darwin-sandbox')

    def test_fresh_work_requires_native_sandbox(self):
        with self.assertRaises(AssertionError):
            verify_actions([self.action(CONSOLE, runner='local')], {CONSOLE}, 'darwin-sandbox')

    def test_recovery_requires_explicit_disk_hits(self):
        for actions in ([], [self.action(name, True, 'action cache hit') for name in PROJECTS],
                        [self.action(CONSOLE, True, 'disk cache hit')]):
            with self.assertRaises(AssertionError):
                verify_actions(actions, set(), 'darwin-sandbox', recovered=True)
        verify_actions([self.action(name, True, 'disk cache hit') for name in PROJECTS],
                       set(), 'darwin-sandbox', recovered=True)

    def test_json_mutations_change_real_generator_data_without_project_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            path = source / SPINNERS
            path.parent.mkdir(parents=True)
            original = dict(Default=dict(interval=100, frames=['a', 'b']), Ascii=dict(interval=100, frames=['x', 'y']))
            for case in ('jsonEdit', 'jsonEntryAdd', 'jsonEntryRemove'):
                path.write_text(json.dumps(original))
                mutate(source, case)
                changed = json.loads(path.read_text())
                self.assertNotEqual(original, changed)
                if case == 'jsonEdit': self.assertEqual(107, changed['Default']['interval'])
                if case == 'jsonEntryAdd': self.assertIn('AcceptanceProbe', changed)
                if case == 'jsonEntryRemove': self.assertNotIn('Ascii', changed)
                self.assertFalse(list(source.rglob('*.csproj')))

    def test_unknown_case_fails(self):
        with self.assertRaises(ValueError):
            mutate(Path('/unused'), 'typo')


if __name__ == '__main__':
    unittest.main()
