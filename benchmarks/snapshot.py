"""Freeze a prepared BUILD workspace for bazel-bench's independent git clones."""
import argparse
from pathlib import Path
import shutil
import subprocess


def snapshot(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.is_relative_to(source):
        raise ValueError('Snapshot must be outside its source workspace')
    def ignore(folder, names):
        # These are outputs of the preparation/build workflows, never fixture inputs.
        outputs = {'bin', 'obj'} if any(n.endswith('.csproj') for n in names) else set()
        return [n for n in names if n in {'.git', '.tools', '.cache', '__pycache__'} | outputs
                or (Path(folder) == source and n.startswith('bazel-'))]
    shutil.copytree(source, output, ignore=ignore, symlinks=False)
    # The snapshot owns its input bytes; git must include ignored locked packages.
    subprocess.run(['git', 'init', str(output)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['git', '-C', str(output), 'add', '--force', '.'], check=True)
    subprocess.run(['git', '-C', str(output), '-c', 'user.name=Benchmark fixture',
                    '-c', 'user.email=benchmark@invalid', 'commit', '-m', 'Prepared benchmark inputs'],
                   check=True, stdout=subprocess.DEVNULL)
    return output


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('workspace', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    snapshot(a.workspace, a.output)
