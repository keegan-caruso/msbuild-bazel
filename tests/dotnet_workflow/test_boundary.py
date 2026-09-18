"""Only test/oracle commands may depend on Python after migration."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]

class ProductionBoundary(unittest.TestCase):
    def test_normal_shell_entry_points_do_not_invoke_python(self):
        for name in ('setup.sh', 'check.sh', 'prepare.sh', 'build.sh', 'tooling.sh', 'env.sh', 'dotnet.sh', 'bazel.sh', 'toolchain-pins.sh'):
            source = '\n'.join(line for line in (ROOT/'scripts'/name).read_text().splitlines() if not line.lstrip().startswith('#'))
            self.assertNotRegex(source, r'\bpython(?:3)?\b|\b[a-z_-]+\.py\b', name)

    def test_controller_has_no_python_process_or_runtime_dependency(self):
        for path in (ROOT/'tools/Preparation').glob('*.cs'):
            source = '\n'.join(line for line in path.read_text().splitlines() if not line.lstrip().startswith('//'))
            self.assertNotRegex(source, r'"[^"\n]*(?:python3?|\.py\b)[^"\n]*"', path.name)
        project = (ROOT/'tools/Preparation/Preparation.csproj').read_text()
        self.assertNotIn('PackageReference', project)

    def test_shell_bootstrap_pins_match_json_for_both_architectures(self):
        import json
        pins = json.loads((ROOT/'scripts/toolchains.json').read_text())
        shell = (ROOT/'scripts/toolchain-pins.sh').read_text()
        sections = shell.split(';;')
        for section, arch in zip(sections, ('x64', 'arm64')):
            for name, pin in pins.items():
                expected = dict(pin, **pin.get('platforms', {}).get('linux-'+arch, {}))
                for field in ('version', 'url', 'sha256'):
                    self.assertRegex(section, re.escape(name+'_'+field+'='+expected[field])+r'\s')
