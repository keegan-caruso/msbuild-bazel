"""Qualify the test-only project-cache plugin on Orchard's pinned CMS graph."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


ROOT = Path(__file__).resolve().parents[3]
PROBE = ROOT / "tests/explicit_msbuild/cache_extension/bin/Release/net10.0/AvaloniaProbe.dll"
ENTRY = "src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj"
BODY = "src/OrchardCore/OrchardCore.Abstractions/Extensions/Manifests/NotFoundManifestInfo.cs"
SMOKE = ROOT / "tests/explicit_msbuild/orchard_compatibility/smoke.py"


def qualify(source: Path, output: Path) -> dict:
    sdk = Path(os.environ["RULES_MSBUILD_DOTNET_ROOT"])
    packages = Path(os.environ["NUGET_PACKAGES"])
    if not PROBE.is_file():
        raise FileNotFoundError(f"Build {PROBE.parents[3] / 'AvaloniaProbe.csproj'} first")
    output.mkdir(parents=True)
    env = dict(os.environ)
    env.update(
        DOTNET_ROOT=str(sdk),
        DOTNET_HOST_PATH=str(sdk / "dotnet"),
        DOTNET_CLI_HOME=str(output / "dotnet-home"),
        DOTNET_CLI_TELEMETRY_OPTOUT="1",
        MSBUILDDISABLENODEREUSE="1",
    )
    (output / "dotnet-home").mkdir()
    results = {}
    runtime_state = source / "src/OrchardCore.Cms.Web/App_Data"
    # The setup smoke creates this untracked runtime tree next to the project.
    # Keep each build's source inputs identical to the pinned checkout.
    shutil.rmtree(runtime_state, ignore_errors=True)

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
        "-p:NuGetAudit=false", f"-p:RestorePackagesPath={packages}",
    ])

    def clean(nodes: list[dict] | None = None) -> None:
        if nodes is None:
            folders = (path for path in source.rglob("Release") if path.parent.name in ("bin", "obj"))
        else:
            folders = (
                (source / node["project"]).parent / kind / "Release"
                for node in nodes for kind in ("bin", "obj")
            )
        for folder in set(folders):
            shutil.rmtree(folder, ignore_errors=True)

    def run(name: str, seed: str | None) -> dict:
        elapsed = execute(name, [
            str(sdk / "dotnet"), "exec", str(PROBE), str(source), ENTRY,
            str(output / seed) if seed else "-", str(output / name),
            str(output / f"{name}.json"), "orchard",
        ])
        report = json.loads((output / f"{name}.json").read_text())
        report["wallSeconds"] = elapsed
        results[name] = report
        print(name, report["graphNodes"], report["hits"], report["misses"], round(elapsed, 3), flush=True)
        return report

    def outputs(nodes: list[dict], include_intermediates: bool) -> dict[str, str]:
        files = {}
        for node in nodes:
            if not node["framework"]:
                continue
            project = (source / node["project"]).parent
            framework = node["framework"]
            prefixes = [f"bin/Release/{framework}"]
            if include_intermediates:
                prefixes.append(f"obj/Release/{framework}")
            else:
                prefixes.extend((f"obj/Release/{framework}/ref", f"obj/Release/{framework}/refint"))
            for relative in prefixes:
                folder = project / relative
                if folder.exists():
                    for path in folder.rglob("*"):
                        if path.is_file():
                            files[str(path.relative_to(source))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return files

    def compare(name: str, actual: dict[str, str], expected: dict[str, str], strict: bool = True) -> list[str]:
        differences = [key for key in actual.keys() | expected.keys() if actual.get(key) != expected.get(key)]
        results[name + "OutputComparison"] = {
            "actualFiles": len(actual), "expectedFiles": len(expected),
            "mismatchCount": len(differences), "mismatchExamples": differences[:20],
        }
        if strict and differences:
            raise AssertionError((name, "output mismatch", differences[:20]))
        return differences

    def smoke(name: str) -> list[dict]:
        try:
            execute("smoke-" + name, [
                "python3", str(SMOKE), str(source), str(output), name, "--raw",
            ])
            return json.loads((output / f"{name}.json").read_text())
        finally:
            shutil.rmtree(runtime_state, ignore_errors=True)

    clean()
    seed = run("seed", None)
    configured = sum(bool(node["framework"]) for node in seed["nodes"])
    seeded_outputs = outputs(seed["nodes"], include_intermediates=True)
    clean(seed["nodes"])
    replay = run("clean-replay", "seed")
    if replay["hits"] != configured:
        raise AssertionError(("clean replay", replay["hits"], configured))
    compare("clean-replay", outputs(seed["nodes"], include_intermediates=True), seeded_outputs)
    smoke("clean-replay-smoke")

    edit = source / BODY
    original = edit.read_text()
    needle = "string Description => null;"
    if original.count(needle) != 1:
        raise AssertionError("Body edit location changed")
    try:
        edit.write_text(original.replace(needle, 'string Description => "cache qualification";'))
        clean(seed["nodes"])
        cached = run("body-cached", "seed")
        if cached["hits"] != configured - 1:
            raise AssertionError(("body edit invalidation", cached["hits"], configured - 1))
        cached_outputs = outputs(seed["nodes"], include_intermediates=False)
        cached_smoke = smoke("body-cached-smoke")
        reference = "src/OrchardCore/OrchardCore.Abstractions/obj/Release/net10.0/ref/OrchardCore.Abstractions.dll"
        if cached_outputs[reference] != seeded_outputs[reference]:
            raise AssertionError("Body edit changed the Abstractions reference assembly")
        clean(seed["nodes"])
        run("body-control", None)
        control_outputs = outputs(seed["nodes"], include_intermediates=False)
        differences = compare("body-cached", cached_outputs, control_outputs, strict=False)
        for relative in (
            "bin/Release/net10.0/OrchardCore.Abstractions.dll",
            "bin/Release/net10.0/OrchardCore.Abstractions.pdb",
            "obj/Release/net10.0/ref/OrchardCore.Abstractions.dll",
        ):
            path = "src/OrchardCore/OrchardCore.Abstractions/" + relative
            if cached_outputs[path] != control_outputs[path]:
                raise AssertionError(("edited project's output mismatch", path))
        results["bodyControlReferenceDifferences"] = [
            path for path in differences if "/ref/" in path or "/refint/" in path
        ]
        control_smoke = smoke("body-control-smoke")
        cached_assets = {row["path"]: row["sha256"] for row in cached_smoke if row["path"] != "/"}
        control_assets = {row["path"]: row["sha256"] for row in control_smoke if row["path"] != "/"}
        if cached_assets != control_assets:
            raise AssertionError(("body edit asset mismatch", cached_assets, control_assets))
    finally:
        edit.write_text(original)

    shutil.rmtree(output / "seed")
    clean(seed["nodes"])
    independent = run("independent-replay", "clean-replay")
    if independent["hits"] != configured:
        raise AssertionError(("independent replay", independent["hits"], configured))
    compare("independent-replay", outputs(seed["nodes"], include_intermediates=True), seeded_outputs)
    results["entry"] = ENTRY
    (output / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="disposable pinned Orchard source root")
    parser.add_argument("output", type=Path, help="fresh result directory")
    args = parser.parse_args()
    qualify(args.source.resolve(), args.output.resolve())
