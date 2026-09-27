"""Select a component's source plus shared VMR build definitions for qualification."""
from pathlib import PurePosixPath
import tarfile

from source_action_prepare import normalize


def includes(name, component):
    path = PurePosixPath(name)
    if name == 'build-native.sh':
        return False
    if not name.startswith('src/') or name.startswith('src/' + component + '/'):
        return True
    if len(path.parts) == 2 or name.startswith('src/arcade/eng/common/'):
        return True
    # Other repositories remain evaluable by upstream's repository graph. Their
    # implementation files are excluded; shared metadata stays explicit.
    return path.suffix.lower() in {'.props', '.targets', '.proj', '.csproj', '.json', '.config', '.xml', '.sln', '.slnx'}


def select(original, component, output, helpers):
    with tarfile.open(original) as source, tarfile.open(output, 'w') as archive:
        for entry in source:
            if entry.isdir() or not includes(entry.name, component):
                continue
            if entry.islnk() and not includes(entry.linkname, component):
                raise ValueError('Component hard link requires excluded source: ' + entry.linkname)
            archive.addfile(normalize(entry), source.extractfile(entry) if entry.isfile() else None)
        for helper in helpers:
            archive.add(helper, arcname='.qualification/' + helper.name, filter=normalize)
