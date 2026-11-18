"""Acquire or verify the pinned native Linux x64 source-SDK bootstrap inputs."""
import argparse
import json
import os
import tempfile
from pathlib import Path
import urllib.request

from inventory import digest


def verify(path, pin):
    if not path.is_file() or path.stat().st_size != pin['bytes'] or digest(path) != pin['sha256']:
        raise ValueError('Acquisition identity mismatch: ' + str(path))


def download(destination, pin):
    if destination.exists():
        verify(destination, pin)
        return
    descriptor, name = tempfile.mkstemp(prefix=destination.name + '.', suffix='.partial', dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as target, urllib.request.urlopen(pin['url'], timeout=120) as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                target.write(block)
        verify(temporary, pin)
        try:
            # Same-directory hardlink publication is atomic and never replaces a final.
            os.link(temporary, destination)
        except FileExistsError:
            verify(destination, pin)
    finally:
        temporary.unlink(missing_ok=True)


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
        if not args.verify:
            download(destination, pin)
        verify(destination, pin)
        print(name + ': verified ' + pin['sha256'], flush=True)


if __name__ == '__main__':
    main()
