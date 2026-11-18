"""Generate x64 bootstrap artifacts through the pinned VMR's stock Restore target."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

from acquire_x64 import verify
from inventory import digest


def prepare(source, pin):
    archive_directory = source / 'prereqs/packages/archive'
    raw = archive_directory / pin['previouslySourceBuiltArtifacts']['url'].rsplit('/', 1)[1]
    verify(raw, pin['previouslySourceBuiltArtifacts'])
    output = archive_directory / 'Private.SourceBuilt.Artifacts.Bootstrap.tar.gz'
    if output.exists():
        raise ValueError('Bootstrap output already exists; use a fresh preparation')
    working = source / 'artifacts/prep-bootstrap'
    working.mkdir(parents=True, exist_ok=False)
    # Match upstream BootstrapArtifacts staging without changing its source. The
    # stock project's AfterTargets=Restore target replaces portable packages and
    # repacks this raw archive into Private.SourceBuilt.Artifacts.Bootstrap.tar.gz.
    with tarfile.open(raw, 'r|gz') as bundle:
        for member in bundle:
            if member.name.removeprefix('./') != 'PackageVersions.props':
                continue
            if not member.isfile():
                raise ValueError('Expected regular PackageVersions.props')
            data = bundle.extractfile(member).read()
            (working / 'PackageVersions.props').write_bytes(data)
            break
        else:
            raise ValueError('Raw source-built archive lacks PackageVersions.props')
    project = source / 'eng/bootstrap/buildBootstrapPreviouslySB.csproj'
    config = source / 'src/sdk/NuGet.config'
    shutil.copyfile(project, working / project.name)
    shutil.copyfile(config, working / 'NuGet.config')
    (source / 'artifacts/log').mkdir(parents=True, exist_ok=True)
    subprocess.run([str(source / '.dotnet/dotnet'), 'restore', str(working / project.name),
                    '/bl:artifacts/log/prep-bootstrap.binlog',
                    '/fileLoggerParameters:LogFile=artifacts/log/prep-bootstrap.log',
                    '/p:ArchiveDir=' + str(archive_directory) + '/', '/p:PortableTargetRid=linux-x64'],
                   cwd=source, check=True)
    if not output.is_file():
        raise ValueError('Upstream Restore target did not create bootstrap archive')
    members = []
    seen = set()
    with tarfile.open(output, 'r|gz') as bundle:
        for member in bundle:
            name = member.name.removeprefix('./')
            if not member.isfile() or '/' in name or name in seen:
                raise ValueError('Unexpected generated bootstrap archive member: ' + member.name)
            seen.add(name)
            checksum = hashlib.sha256()
            stream = bundle.extractfile(member)
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                checksum.update(block)
            members.append({'name': name, 'bytes': member.size, 'sha256': checksum.hexdigest()})
    if 'PackageVersions.props' not in {entry['name'] for entry in members} or not any(entry['name'].endswith('.nupkg') for entry in members):
        raise ValueError('Generated bootstrap archive lacks package inventory')
    report = {'portableRid': 'linux-x64', 'rawArchiveSha256': pin['previouslySourceBuiltArtifacts']['sha256'],
              'projectSha256': digest(project), 'nugetConfigSha256': digest(config),
              'bootstrapArchiveSha256': digest(output), 'bootstrapArchiveBytes': output.stat().st_size,
              'members': members}
    (source / 'artifacts/log/bootstrap-inputs.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    pin = json.loads(Path(__file__).with_name('pin-linux-x64.json').read_text())
    print(json.dumps(prepare(args.source.resolve(), pin), indent=2))


if __name__ == '__main__':
    main()
