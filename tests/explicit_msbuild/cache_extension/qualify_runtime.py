"""Qualify the test-only project cache on a disposable dotnet/runtime checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parents[3]
PROBE = ROOT / "tests/explicit_msbuild/cache_extension/bin/Release/net10.0/AvaloniaProbe.dll"
ENTRY = "src/libraries/System.IO.Pipelines/src/System.IO.Pipelines.csproj"
BODY = "src/libraries/System.IO.Pipelines/src/System/IO/Pipelines/ThrowHelper.cs"
REFERENCE = "artifacts/bin/System.IO.Pipelines/ref/Release/net10.0/System.IO.Pipelines.dll"
IMPLEMENTATION = "artifacts/bin/System.IO.Pipelines/Release/net10.0/System.IO.Pipelines.dll"
NEEDLE = "new InvalidOperationException(SR.ReadingIsInProgress);"
EDITED = 'new InvalidOperationException(SR.ReadingIsInProgress + " cache probe");'


def qualify(source: Path, output: Path) -> dict:
    sdk = Path(os.environ["RULES_MSBUILD_DOTNET_ROOT"])
    packages = Path(os.environ["NUGET_PACKAGES"])
    if not PROBE.is_file():
        raise FileNotFoundError(f"Build {PROBE.parents[3] / 'AvaloniaProbe.csproj'} first")
    if (source / "artifacts/bin").exists():
        raise ValueError("Use a disposable source copy without built outputs")
    output.mkdir(parents=True, exist_ok=False)
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
    properties = [
        "-p:TargetArchitecture=arm64", "-p:TargetOS=osx",
        "-p:UseLocalTargetingRuntimePack=false", "-p:RestoreUseStaticGraphEvaluation=false",
        "-p:NuGetAudit=false", "-p:UseSharedCompilation=false",
        f"-p:NetCoreSdkRoot={sdk / 'sdk/10.0.400'}",
    ]

    def execute(name: str, command: list[str]) -> float:
        started = time.perf_counter()
        with (output / f"{name}.log").open("w") as log:
            completed = subprocess.run(command, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT)
        elapsed = time.perf_counter() - started
        if completed.returncode:
            raise RuntimeError(f"{name} failed; see {output / (name + '.log')}")
        return elapsed

    execute("restore", [str(sdk / "dotnet"), "restore", ENTRY, *properties])

    def run(name: str, previous: str | None) -> dict:
        elapsed = execute(name, [
            str(sdk / "dotnet"), "exec", str(PROBE), str(source), ENTRY,
            str(output / previous) if previous else "-", str(output / name),
            str(output / f"{name}.json"), "runtime",
        ])
        report = json.loads((output / f"{name}.json").read_text())
        results[name] = {key: report[key] for key in (
            "graphNodes", "hits", "misses", "graphSeconds", "buildSeconds",
            "snapshotSeconds", "totalSeconds", "success",
        )}
        results[name]["wallSeconds"] = elapsed
        print(name, report["hits"], report["misses"], round(elapsed, 3), flush=True)
        return report

    def manifests(name: str) -> dict[str, dict]:
        cache = output / name
        return {str(path.relative_to(cache)): json.loads(path.read_text())
                for path in cache.rglob("manifest.json")}

    def clean(name: str) -> None:
        files = {path for manifest in manifests(name).values()
                 for path in (*manifest["Files"], *manifest["ProjectCopies"])}
        for relative in files:
            if not relative.startswith("artifacts/") or ".." in Path(relative).parts:
                raise ValueError(f"Unsafe output path: {relative}")
            (source / relative).unlink(missing_ok=True)

    def digest(path: str) -> str:
        return hashlib.sha256((source / path).read_bytes()).hexdigest()

    def file_hash(name: str, relative: str) -> str:
        matches = [manifest["Files"][relative] for manifest in manifests(name).values()
                   if relative in manifest["Files"]]
        if len(matches) != 1:
            raise AssertionError((name, relative, len(matches)))
        return matches[0]

    seed = run("seed", None)
    configured = sum(bool(node["framework"]) for node in seed["nodes"])
    seed_manifests = manifests("seed")
    results["snapshotFiles"] = sum(len(manifest["Files"]) for manifest in seed_manifests.values())
    results["producerCopies"] = sum(len(manifest["ProjectCopies"]) for manifest in seed_manifests.values())
    clean("seed")
    replay = run("clean-replay", "seed")
    if replay["hits"] != configured or manifests("clean-replay") != seed_manifests:
        raise AssertionError("Clean replay differed from the seed")
    for manifest in seed_manifests.values():
        for relative, expected in manifest["Files"].items():
            if digest(relative) != expected:
                raise AssertionError(("replayed output", relative))
        for relative, producer in manifest["ProjectCopies"].items():
            if digest(relative) != digest(producer):
                raise AssertionError(("replayed producer copy", relative, producer))

    edit = source / BODY
    original = edit.read_text()
    if original.count(NEEDLE) != 1:
        raise AssertionError("Body edit location changed")
    try:
        edit.write_text(original.replace(NEEDLE, EDITED))
        clean("seed")
        cached = run("body-cached", "seed")
        if cached["hits"] != configured - 1:
            raise AssertionError(("body edit invalidation", cached["hits"], configured - 1))
        if file_hash("body-cached", REFERENCE) != file_hash("seed", REFERENCE):
            raise AssertionError("Body edit changed the Pipelines contract")
        if file_hash("body-cached", IMPLEMENTATION) == file_hash("seed", IMPLEMENTATION):
            raise AssertionError("Body edit did not change the Pipelines implementation")
        clean("seed")
        run("body-control", None)
        results["bodyControlManifestEqual"] = manifests("body-cached") == manifests("body-control")
        cached_bins = {path: expected for manifest in manifests("body-cached").values()
                       for path, expected in manifest["Files"].items()
                       if path.startswith("artifacts/bin/")}
        control_bins = {path: expected for manifest in manifests("body-control").values()
                        for path, expected in manifest["Files"].items()
                        if path.startswith("artifacts/bin/")}
        results["bodyControlBinFiles"] = len(cached_bins)
        if cached_bins != control_bins:
            raise AssertionError("Edited runtime binaries differ from the no-cache control")
        results["bodyControlImplementationEqual"] = (
            file_hash("body-cached", IMPLEMENTATION) == file_hash("body-control", IMPLEMENTATION)
        )
        if not results["bodyControlImplementationEqual"]:
            raise AssertionError("Edited Pipelines DLL differed from the no-cache control")
    finally:
        edit.write_text(original)

    clean("seed")
    independent = run("independent-replay", "clean-replay")
    if independent["hits"] != configured or manifests("independent-replay") != seed_manifests:
        raise AssertionError("Derived replay differed from the seed")
    (output / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="disposable dotnet/runtime source root")
    parser.add_argument("output", type=Path, help="new results directory")
    args = parser.parse_args()
    qualify(args.source.resolve(), args.output.resolve())
