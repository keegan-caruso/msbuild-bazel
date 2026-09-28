"""Derive a deterministic, bounded Linux ARM64 AOT archive from a tool tree.

This is a qualification helper, not toolchain acquisition. The caller must
supply the source tree and its expected content digest independently.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tarfile


BINARIES = {
    "sh", "dash", "clang", "llvm-objcopy", "objcopy",
    "aarch64-linux-gnu-objcopy", "ld", "ld.bfd",
    "aarch64-linux-gnu-ld", "aarch64-linux-gnu-ld.bfd",
    "as", "aarch64-linux-gnu-as",
}
LLVM_BINARIES = {"clang", "clang-14", "llvm-objcopy"}
SYSTEM_ARCHIVES = {"libc.a", "libc_nonshared.a", "libpthread.a", "libdl.a", "librt.a", "libm.a"}
ETC_FILES = {"os-release", "ld.so.cache", "passwd", "group"}


def selected(relative):
    parts = relative.parts
    if parts[0] not in ("usr", "etc"):
        return False
    if parts[0] == "etc":
        return len(parts) == 2 and parts[1] in ETC_FILES
    if parts[:2] == ("usr", "bin"):
        return len(parts) == 3 and parts[2] in BINARIES
    if parts[:4] == ("usr", "lib", "llvm-14", "bin"):
        return len(parts) == 5 and parts[4] in LLVM_BINARIES
    if parts[:4] == ("usr", "lib", "llvm-14", "lib"):
        if len(parts) > 4 and parts[4] == "cmake":
            return False
        if len(parts) == 5 and relative.suffix == ".a":
            return False
        if parts[4:8] == ("clang", "14.0.0", "lib", "linux"):
            return False
    if parts[:3] == ("usr", "lib", "llvm-14") and len(parts) > 3 and parts[3] in ("include", "share"):
        return False
    if parts[:3] == ("usr", "include", "llvm-14"):
        return False
    if parts[:3] in {
        ("usr", "lib", "apt"), ("usr", "lib", "git-core"),
        ("usr", "lib", "python3"), ("usr", "lib", "python3.10"),
    }:
        return False
    if parts[:3] == ("usr", "lib", "aarch64-linux-gnu"):
        if len(parts) > 3 and parts[3] in ("perl", "perl-base", "gconv"):
            return False
        if len(parts) == 4 and relative.suffix == ".a" and parts[3] not in SYSTEM_ARCHIVES:
            return False
    if parts[:5] == ("usr", "lib", "gcc", "aarch64-linux-gnu", "11") and len(parts) == 6 and parts[5] in ("cc1", "lto1"):
        return False
    return True


def entries(root):
    root = root.resolve()
    files = {path.relative_to(root) for path in root.rglob("*") if (path.is_file() or path.is_symlink()) and selected(path.relative_to(root))}
    # Links to host-absolute paths are not portable. Drop links whose targets
    # were removed by the selection too, repeating until chains stabilize.
    while True:
        removed = set()
        for relative in files:
            path = root / relative
            if not path.is_symlink():
                continue
            target = path.readlink()
            if target.is_absolute():
                removed.add(relative)
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(root) or not resolved.exists():
                removed.add(relative)
                continue
            target_relative = resolved.relative_to(root)
            if target_relative not in files and not any(item.is_relative_to(target_relative) for item in files):
                removed.add(relative)
        if not removed:
            break
        files -= removed
    directories = {Path(*relative.parts[:index]) for relative in files for index in range(1, len(relative.parts))}
    return sorted(directories | files, key=lambda p: p.as_posix())


def digest_tree(root):
    root = root.resolve()
    digest = hashlib.sha256()
    for relative in entries(root):
        path = root / relative
        if path.is_dir() and not path.is_symlink():
            continue
        digest.update(relative.as_posix().encode() + b"\0")
        digest.update(str(path.lstat().st_mode & 0o7777).encode() + b"\0")
        if path.is_symlink():
            digest.update(b"link\0" + str(path.readlink()).encode() + b"\0")
        else:
            digest.update(b"file\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def archive(root, output):
    root = root.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream, gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as compressed, tarfile.open(fileobj=compressed, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for relative in entries(root):
            path = root / relative
            info = tar.gettarinfo(str(path), arcname=relative.as_posix())
            info.uid = info.gid = info.mtime = 0
            info.uname = info.gname = ""
            if info.isfile():
                with path.open("rb") as content:
                    tar.addfile(info, content)
            else:
                tar.addfile(info)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--expected-tree-sha256", required=True)
    parser.add_argument("--expected-archive-sha256")
    args = parser.parse_args()
    root = args.source.resolve()
    if not (root / "usr").is_dir() or not (root / "etc").is_dir():
        parser.error("source tree must contain usr and etc")
    if args.output.resolve().is_relative_to(root):
        parser.error("output archive must be outside the source tree")
    actual = digest_tree(root)
    if actual != args.expected_tree_sha256:
        parser.error(f"selected source tree differs from locked SHA-256: {actual}")
    archive(root, args.output)
    output_digest = hashlib.sha256()
    with args.output.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            output_digest.update(chunk)
    output_hash = output_digest.hexdigest()
    if args.expected_archive_sha256 and output_hash != args.expected_archive_sha256:
        args.output.unlink()
        parser.error(f"archive differs from locked SHA-256: {output_hash}")
    print(json.dumps({"selectedTreeSha256": actual, "archiveSha256": output_hash, "bytes": args.output.stat().st_size}))


if __name__ == "__main__":
    main()
