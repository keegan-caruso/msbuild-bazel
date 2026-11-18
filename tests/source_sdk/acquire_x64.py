"""Acquire or verify the pinned native Linux x64 source-SDK bootstrap inputs."""
import argparse
import json
from pathlib import Path
import urllib.request

from inventory import digest


def verify(path, pin):
    if not path.is_file() or path.stat().st_size != pin['bytes'] or digest(path) != pin['sha256']:
        raise ValueError('Acquisition identity mismatch: ' + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    pins = json.loads(Path(__file__).with_name('pin-linux-x64.json').read_text())
    args.directory.mkdir(parents=True, exist_ok=True)
    for name in ['bootstrapSdk', 'previouslySourceBuiltArtifacts', 'controllerSdk']:
        pin = pins[name]
        destination = args.directory / pin['url'].rsplit('/', 1)[1]
        if not args.verify and not destination.exists():
            temporary = destination.with_suffix(destination.suffix + '.partial')
            try:
                with urllib.request.urlopen(pin['url'], timeout=120) as source, temporary.open('xb') as target:
                    for block in iter(lambda: source.read(1024 * 1024), b''):
                        target.write(block)
                verify(temporary, pin)
                temporary.rename(destination)
            finally:
                temporary.unlink(missing_ok=True)
        verify(destination, pin)
        print(name + ': verified ' + pin['sha256'], flush=True)


if __name__ == '__main__':
    main()
