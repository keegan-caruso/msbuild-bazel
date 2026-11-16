#!/usr/bin/env python3
"""Install only the exact recorded source-SDK prerequisite package overlay."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

MANIFEST = Path(__file__).with_name('packages.json')


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def validate_archive(path, package, inspect):
    if digest(path) != package['sha256']:
        raise ValueError('Package SHA256 mismatch: ' + package['name'])
    if inspect(path) != (package['name'], package['version'], package['architecture']):
        raise ValueError('Package identity mismatch: ' + package['name'])


def inspect_deb(path):
    output = subprocess.check_output(['dpkg-deb', '-f', str(path), 'Package', 'Version', 'Architecture'], text=True)
    fields = dict(line.split(': ', 1) for line in output.splitlines())
    return fields['Package'], fields['Version'], fields['Architecture']


def stage_verified_archive(path, package, inspect, cache):
    validate_archive(path, package, inspect)
    destination = cache/path.name
    if destination.exists():
        raise ValueError('Duplicate cached archive: ' + path.name)
    shutil.copyfile(path, destination)
    return destination


def offline_command(cache, packages):
    return ['apt-get', '-o', 'Dir::Cache::archives=' + str(cache), '--no-download',
            '--no-install-recommends', 'install'] + [p['name'] + '=' + p['version'] for p in packages]


def validate_transaction(output, allowed):
    for line in output.splitlines():
        line = line.strip()
        if line.startswith(('Remv ', 'Purg ')):
            raise ValueError('Overlay would remove a package: ' + line)
        if line.startswith('Inst '):
            name = line.split()[1].split(':', 1)[0]
            if name not in allowed:
                raise ValueError('Overlay requires an unlisted package: ' + name)


def simulate_transaction(command, environment, allowed):
    try:
        output = subprocess.check_output(command[:1] + ['-s'] + command[1:], text=True,
                                         env=environment, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as error:
        print(error.output, file=sys.stderr, end='')
        raise
    validate_transaction(output, allowed)


def validate_base(reference, release, architecture, clang_version):
    if not re.fullmatch(r'[^\s@]+@sha256:[0-9a-f]{64}', reference):
        raise ValueError('NATIVE_BASE must be an immutable image reference')
    if release.get('ID') != 'ubuntu' or release.get('VERSION_ID') != '26.04' or architecture != 'arm64':
        raise ValueError('Source SDK overlay requires Ubuntu 26.04 ARM64')
    if 'clang version 18.1.8' not in clang_version:
        raise ValueError('Source SDK overlay requires Clang 18.1.8')


def main():
    if len(sys.argv) != 2:
        raise ValueError('Expected immutable NATIVE_BASE image reference')
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    release = {key: value.strip('\"') for key, value in release.items()}
    validate_base(sys.argv[1], release,
                  subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip(),
                  subprocess.check_output(['clang-18', '--version'], text=True))
    manifest = json.loads(MANIFEST.read_text())
    packages = manifest['packages']
    if manifest['version'] != 1 or len(packages) != 17:
        raise ValueError('Unexpected prerequisite manifest')
    names = [p['name'] for p in packages]
    if len(set(names)) != len(names):
        raise ValueError('Duplicate prerequisite package')
    for p in packages:
        if (set(p) != {'name', 'version', 'architecture', 'sha256'} or
                not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', p['name']) or
                p['architecture'] not in ('arm64', 'all') or
                not re.fullmatch(r'[0-9a-f]{64}', p['sha256'])):
            raise ValueError('Invalid prerequisite package metadata')
    os.environ['DEBIAN_FRONTEND'] = 'noninteractive'
    subprocess.run(['apt-get', 'update', '-qq'], check=True)
    with tempfile.TemporaryDirectory(prefix='source-sdk-overlay-') as temporary:
        root = Path(temporary)
        root.chmod(0o755)
        downloads = root/'debs'; downloads.mkdir()
        cache = root/'cache'; cache.mkdir(); (cache/'partial').mkdir()
        for p in packages:
            before = set(downloads.iterdir())
            subprocess.run(['apt-get', 'download', p['name'] + '=' + p['version']], cwd=downloads, check=True)
            added = set(downloads.iterdir()) - before
            if len(added) != 1:
                raise ValueError('Expected exactly one downloaded package: ' + p['name'])
            archive = added.pop()
            stage_verified_archive(archive, p, inspect_deb, cache)
        # The private cache contains only verified archives; no download is allowed.
        command = offline_command(cache, packages)
        environment = dict(os.environ, LC_ALL='C')
        simulate_transaction(command, environment, set(names))
        subprocess.run(command[:1] + ['-y'] + command[1:], check=True, env=environment)
        for p in packages:
            actual = subprocess.check_output(['dpkg-query', '-W', '-f=${Version} ${Architecture}', p['name']], text=True).strip()
            if actual != p['version'] + ' ' + p['architecture']:
                raise ValueError('Installed package identity differs: ' + p['name'])
    output = Path('/opt/source-sdk-prerequisites'); output.mkdir(parents=True, exist_ok=True)
    (output/'packages.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output/'base-image.txt').write_text(sys.argv[1] + '\n')
    inventory = subprocess.check_output(['dpkg-query', '-W'], text=True)
    (output/'installed.tsv').write_text(inventory)


if __name__ == '__main__':
    main()
