"""Qualify the cache extension against Avalonia's pinned SimpleTheme graph."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PROBE = ROOT / "tests/explicit_msbuild/cache_extension/bin/Release/net10.0/AvaloniaProbe.dll"
ENTRY = "src/Avalonia.Themes.Simple/Avalonia.Themes.Simple.csproj"
BODY = "src/Avalonia.Base/Media/PolylineGeometry.cs"
XAML = "src/Avalonia.Themes.Simple/SimpleTheme.xaml"


def qualify(source: Path, output: Path) -> dict:
    sdk = Path(os.environ["RULES_MSBUILD_DOTNET_ROOT"])
    packages = Path(os.environ["NUGET_PACKAGES"])
    env = dict(os.environ)
    env.update(
        DOTNET_ROOT=str(sdk),
        DOTNET_HOST_PATH=str(sdk / "dotnet"),
        DOTNET_CLI_HOME=str(output / "dotnet-home"),
        DOTNET_CLI_TELEMETRY_OPTOUT="1",
        MSBUILDDISABLENODEREUSE="1",
    )
    output.mkdir(parents=True)
    (output / "dotnet-home").mkdir()
    reports = {}

    def execute(name: str, command: list[str]) -> float:
        started = time.perf_counter()
        result = subprocess.run(command, cwd=source, env=env, capture_output=True, text=True)
        elapsed = time.perf_counter() - started
        (output / f"{name}.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f"{name} failed; see {output / (name + '.log')}")
        return elapsed

    execute("restore", [
        str(sdk / "dotnet"), "restore", str(source / ENTRY),
        "-p:AvsSkipBuildingLegacyTargetFrameworks=True", "-p:NuGetAudit=false",
        f"-p:RestorePackagesPath={packages}",
    ])

    def run(name: str, seed: str | None) -> dict:
        elapsed = execute(name, [
            str(sdk / "dotnet"), "exec", str(PROBE), str(source), ENTRY,
            str(output / seed) if seed else "-", str(output / name),
            str(output / f"{name}.json"),
        ])
        report = json.loads((output / f"{name}.json").read_text())
        report["wallSeconds"] = elapsed
        reports[name] = report
        print(name, report["graphNodes"], report["hits"], report["misses"], round(elapsed, 3), flush=True)
        return report

    def clean(nodes: list[dict]) -> None:
        for row in nodes:
            folder = (source / row["project"]).parent
            for relative in ("bin/Release", "obj/Release"):
                shutil.rmtree(folder / relative, ignore_errors=True)

    def manifests(name: str) -> dict[str, dict]:
        folder = output / name
        return {
            str(path.relative_to(folder)): json.loads(path.read_text())["Files"]
            for path in folder.rglob("manifest.json")
        }

    def compare(name: str, control: str) -> None:
        cached = manifests(name)
        clean_build = manifests(control)
        if cached != clean_build:
            differing = [key for key in cached.keys() | clean_build.keys() if cached.get(key) != clean_build.get(key)]
            raise AssertionError((name, "owned output mismatch", differing))

    def manifest(name: str, project: str, framework: str) -> dict:
        path = output / name / f"{project}.{framework}.cache" / "manifest.json"
        return json.loads(path.read_text())["Files"]

    seed = run("seed", None)
    inner = sum(bool(node["framework"]) for node in seed["nodes"])
    clean(seed["nodes"])
    replay = run("clean-replay", "seed")
    if replay["hits"] != inner or replay["misses"] != seed["graphNodes"] - inner:
        raise AssertionError(("clean replay", replay))
    compare("clean-replay", "seed")

    cases = [
        ("xaml", XAML, "</Styles>", '<Style Selector="Button"><Setter Property="Opacity" Value="0.75137" /></Style></Styles>'),
        ("body", BODY, "context.EndFigure(isFilled);", "context.EndFigure(isFilled && Points.Count > 0);"),
        ("api", BODY, "public class PolylineGeometry : Geometry\n    {", "public class PolylineGeometry : Geometry\n    {\n        public bool CacheQualificationMarker => true;"),
    ]
    for name, relative, needle, replacement in cases:
        path = source / relative
        original = path.read_text()
        if original.count(needle) != 1:
            raise AssertionError((name, "edit location changed"))
        path.write_text(original.replace(needle, replacement))
        try:
            clean(seed["nodes"])
            cached = run(name + "-cached", "seed")
            clean(seed["nodes"])
            control = run(name + "-control", None)
            compare(name + "-cached", name + "-control")
            if control["hits"] != 0 or control["misses"] != seed["graphNodes"]:
                raise AssertionError((name, "control used cache", control))
            if cached["hits"] == 0 or cached["misses"] == 0:
                raise AssertionError((name, "edit was not selective", cached))
            if name == "body":
                project = "src/Avalonia.Base/Avalonia.Base.csproj"
                for framework in ("net8.0", "netstandard2.0"):
                    relative_ref = f"obj/Release/{framework}/ref/Avalonia.Base.dll"
                    if manifest("seed", project, framework)[relative_ref] != manifest(name + "-cached", project, framework)[relative_ref]:
                        raise AssertionError((name, framework, "reference changed"))
        finally:
            path.write_text(original)
    raw = [
        str(sdk / "dotnet"), "build", str(source / ENTRY), "-f", "net8.0", "-c", "Release",
        "--no-restore", "-m:4", "-p:AvsSkipBuildingLegacyTargetFrameworks=True",
        "-p:NuGetAudit=false", f"-p:RestorePackagesPath={packages}",
        "-p:DebugType=portable", "-p:ProduceReferenceAssembly=true",
    ]
    raw_times = {"baseline": execute("raw-baseline", raw)}
    for name, relative, needle, replacement in cases:
        path = source / relative
        original = path.read_text()
        path.write_text(original.replace(needle, replacement))
        try:
            raw_times[name] = execute("raw-" + name, raw)
        finally:
            path.write_text(original)
        execute("raw-reset-" + name, raw)
    reports["rawBuildSeconds"] = raw_times
    (output / "summary.json").write_text(json.dumps(reports, indent=2) + "\n")
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="pinned Avalonia source root")
    parser.add_argument("output", type=Path, help="fresh result directory")
    args = parser.parse_args()
    qualify(args.source.resolve(), args.output.resolve())
