"""Prepare a declared Bazel cache-extension comparison from a restored Avalonia tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EXTRA = {
    "microsoft.bcl.asyncinterfaces/6.0.0": "e3df87fe2170a7e01f0880af59caa8f6eb380b3c40a4f282dfb43912aaf0f895",
    "system.componentmodel.annotations/4.5.0": "d79c84d8da13f6f98bf681826b11c29504758cb5b58f579fe611cc839e7146ca",
    "system.diagnostics.diagnosticsource/8.0.1": "ce6c078dc26029c6e49307a91f4dfc421727b16309707cacf8f11b1460b4260a",
}


def prepare(source: Path, destination: Path, packages: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    lock = {key.lower(): value["sha256"] for key, value in json.loads(
        (ROOT / "docs/avalonia-xaml-package-lock.json").read_text()
    ).items()}
    lock.update(EXTRA)
    required = set()
    for assets in source.rglob("project.assets.json"):
        libraries = json.loads(assets.read_text())["libraries"]
        required.update(key.lower() for key, value in libraries.items() if value["type"] == "package")
    # Targeting packs can be acquired by the SDK without appearing in the
    # ordinary libraries section of project.assets.json.
    required.update(lock)
    archives = destination / "locked-packages"
    archives.mkdir()
    for key in sorted(required):
        name, version = key.split("/")
        archive = packages / name / version / f"{name}.{version}.nupkg"
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual != lock.get(key):
            raise ValueError(f"Unpinned or mismatched package {key}: {actual}")
        shutil.copy2(archive, archives / archive.name)

    def ignored(_folder: str, names: list[str]) -> set[str]:
        return set(names) & {".git", "bin", "obj", "artifacts", "._*"}

    for variant in ("Base", "Xaml", "Body", "Api"):
        shutil.copytree(source, destination / variant, ignore=ignored)
    edits = {
        "Xaml": ("src/Avalonia.Themes.Simple/SimpleTheme.xaml", "</Styles>",
                 '<Style Selector="Button"><Setter Property="Opacity" Value="0.75137" /></Style></Styles>'),
        "Body": ("src/Avalonia.Base/Media/PolylineGeometry.cs", "context.EndFigure(isFilled);",
                 "context.EndFigure(isFilled && Points.Count > 0);"),
        "Api": ("src/Avalonia.Base/Media/PolylineGeometry.cs", "public class PolylineGeometry : Geometry\n    {",
                "public class PolylineGeometry : Geometry\n    {\n        public bool CacheQualificationMarker => true;"),
    }
    for variant, (relative, needle, replacement) in edits.items():
        path = destination / variant / relative
        original = path.read_text()
        if original.count(needle) != 1:
            raise AssertionError((variant, "edit location changed"))
        path.write_text(original.replace(needle, replacement))

    os_name = {"Darwin": "osx", "Linux": "linux"}[platform.system()]
    cpu = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64"}[platform.machine()]
    (destination / "MODULE.bazel").write_text(
        'module(name="avalonia_cache_probe")\n'
        'bazel_dep(name="rules_msbuild",version="0.0.0")\n'
        f'local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})\n'
        'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
        f'dotnet.sdk(name="dotnet",version="10.0.400",platforms={json.dumps([os_name + "-" + cpu])})\n'
        'use_repo(dotnet,"dotnet")\n'
    )
    (destination / ".bazelversion").write_text("9.2.0\n")
    lines = [
        'load("@rules_msbuild//tests/explicit_msbuild/cache_extension:graph_probe.bzl", "probe_binary")',
        'load("@rules_msbuild//tests/explicit_msbuild/cache_extension:avalonia_graph.bzl", "avalonia_group")',
        'probe_binary(name="probe",dotnet="@dotnet//:dotnet",sdk="@dotnet//:files",',
        '  project="@rules_msbuild//tests/explicit_msbuild/cache_extension:AvaloniaProbe.csproj",',
        '  sources="@rules_msbuild//tests/explicit_msbuild/cache_extension:avalonia_sources")',
    ]
    for name, variant, seed in [
        ("seed", "Base", None),
        ("xaml_control", "Xaml", None), ("xaml", "Xaml", ":seed"),
        ("body_control", "Body", None), ("body", "Body", ":seed"),
        ("api_control", "Api", None), ("api", "Api", ":seed"),
    ]:
        lines.extend([
            f'avalonia_group(name="{name}",source_root="{variant}",',
            f'  srcs=glob(["{variant}/**", "{variant}/**/.*"]),archives=glob(["locked-packages/*.nupkg"]),',
            '  dotnet="@dotnet//:dotnet",sdk="@dotnet//:files",probe=":probe",',
            f'  seed={json.dumps(seed) if seed else "None"})',
        ])
    (destination / "BUILD.bazel").write_text("\n".join(lines) + "\n")
    (destination / "package-list.json").write_text(json.dumps(sorted(required), indent=2) + "\n")
    print(f"prepared {destination} with {len(required)} pinned NuGet archives")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("packages", type=Path)
    args = parser.parse_args()
    prepare(args.source.resolve(), args.destination.resolve(), args.packages.resolve())
