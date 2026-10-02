"""Run the committed graph example as an independent Bazel consumer."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    with tempfile.TemporaryDirectory(prefix='graph-quickstart-') as temporary:
        root = Path(temporary).resolve()
        workspace = root / 'app'
        shutil.copytree(ROOT / 'examples/quickstart', workspace)
        (root / 'msbuild-bazel').symlink_to(ROOT, target_is_directory=True)
        command = [str(ROOT / 'scripts/bazel-launcher.sh'), f'--output_base={root / "bazel"}']

        def bazel(*arguments):
            result = subprocess.run(command + list(arguments), cwd=workspace, env=os.environ, text=True, capture_output=True)
            assert result.returncode == 0, result.stdout + result.stderr
            return result.stdout + result.stderr

        try:
            bazel('run', '//:sync', '--', '--check')
            assert 'Hello from MSBuild and Bazel' in bazel('run', '//:app')
            bazel('test', '//:tests', '--test_output=errors')
            bazel('run', '//:sync', '--', '--check')
            print('PASS: committed graph quickstart sync/check, run and test')
        finally:
            bazel('shutdown')


if __name__ == '__main__':
    main()
