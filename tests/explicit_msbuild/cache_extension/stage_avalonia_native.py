"""Stage Avalonia's pinned macOS binary package for the Desktop graph probe."""

from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path


PACKAGE_SHA256 = "d6e8cb99868bd734e0b65b0d7ab043b53ba86895fb73b1ee90d2c921a96b0784"
PACKAGE_MEMBER = "runtimes/osx/native/libAvaloniaNative.dylib"
DESTINATION = "Build/Products/Release/libAvalonia.Native.OSX.dylib"


def stage(source: Path, package: Path) -> Path:
    if "<Version>11.3.12</Version>" not in (source / "build/SharedVersion.props").read_text():
        raise ValueError("expected Avalonia source version 11.3.12")
    archive = package.read_bytes()
    digest = hashlib.sha256(archive).hexdigest()
    if digest != PACKAGE_SHA256:
        raise ValueError(f"Avalonia.Native package digest mismatch: {digest}")
    with zipfile.ZipFile(package) as payload:
        library = payload.read(PACKAGE_MEMBER)
    destination = source / DESTINATION
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(library)
    temporary.replace(destination)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Avalonia 11.3.12 source copy")
    parser.add_argument("package", type=Path, help="Avalonia.Native 11.3.12 nupkg")
    args = parser.parse_args()
    print(stage(args.source.resolve(), args.package.resolve()))
