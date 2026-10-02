"""Qualify ordinary edited graph builds against a Bazel HTTP cache service."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from qualify import graph


ROOT = Path(__file__).resolve().parents[3]
DOTNET = Path(os.environ.get("RULES_MSBUILD_DOTNET_ROOT", ROOT / ".tools/dotnet")) / "dotnet"
PROBE = ROOT / "tests/explicit_msbuild/cache_extension/bin/Release/net10.0/CacheProbe.dll"


def run(workspace: Path, name: str, endpoint: str | None, source_name: str | None = None, read_cache: str = "-") -> dict:
    source = workspace / (source_name or name)
    entry = source / "P2/P2.csproj"
    empty = workspace / "empty"
    empty.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["DOTNET_ROOT"] = str(DOTNET.parent)
    if endpoint is None:
        env.pop("RULES_MSBUILD_PROJECT_CACHE_URL", None)
    else:
        env["RULES_MSBUILD_PROJECT_CACHE_URL"] = endpoint
    restore = subprocess.run(
        [str(DOTNET), "restore", str(entry), "--source", str(empty), "-p:NuGetAudit=false"],
        env=env, capture_output=True, text=True,
    )
    if restore.returncode:
        raise RuntimeError(f"{name} restore failed: {restore.stdout}\n{restore.stderr}")
    cache = workspace / (name + "-snapshot")
    result = subprocess.run(
        [str(DOTNET), "exec", str(PROBE), str(source), "P2/P2.csproj", read_cache, str(cache)],
        env=env, capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError(f"{name} build failed: {result.stdout}\n{result.stderr}")
    app = source / "P2/bin/Release/net10.0/P2.dll"
    execution = subprocess.run([str(DOTNET), "exec", str(app)], capture_output=True, text=True, env=env)
    if execution.returncode or execution.stdout.strip() != ("2" if name != "base" else "1"):
        raise AssertionError((name, execution.returncode, execution.stdout, execution.stderr))
    return json.loads((cache / "report.json").read_text())


def outputs(workspace: Path, name: str, source_name: str | None = None) -> dict[str, str]:
    captured = {}
    for project in ("P0", "P1", "P2"):
        manifest = workspace / (name + "-snapshot") / project / (project + ".csproj.cache") / "manifest.json"
        for relative, digest in json.loads(manifest.read_text())["Files"].items():
            captured[f"{project}/{relative}"] = digest
    app = workspace / (source_name or name) / "P2/bin/Release/net10.0"
    for file in app.iterdir():
        if file.is_file():
            captured["app/" + file.name] = hashlib.sha256(file.read_bytes()).hexdigest()
    return captured


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("endpoint", help="Bazel HTTP cache URL, for example http://127.0.0.1:9090")
    parser.add_argument("--output", type=Path, help="Keep the qualification workspace for inspection")
    args = parser.parse_args()
    if not PROBE.is_file():
        raise FileNotFoundError(f"Build {PROBE} first")
    if args.output:
        args.output.mkdir(parents=True, exist_ok=False)
    with nullcontext(args.output) if args.output else tempfile.TemporaryDirectory(prefix="rules-msbuild-remote-") as temporary:
        workspace = Path(temporary)
        salt = uuid.uuid4().hex
        for name, variant in (("base", "Base"), ("edit", "Body")):
            graph(workspace, variant, 3)
            source = workspace / variant
            for project in source.glob("*/*.csproj"):
                project.write_text(project.read_text().replace(
                    "</PropertyGroup>", f"<RemoteQualificationSalt>{salt}</RemoteQualificationSalt></PropertyGroup>",
                ))
            source.rename(workspace / name)
            shutil.copy2(ROOT / "global.json", workspace / name / "global.json")
        shutil.copytree(workspace / "edit", workspace / "recovered")
        shutil.copytree(workspace / "edit", workspace / "other-path-control")
        results = {name: run(workspace, name, args.endpoint) for name in ("base", "edit", "recovered")}
        edited = outputs(workspace, "edit")
        recovered = outputs(workspace, "recovered")
        results["other-path-control"] = run(workspace, "other-path-control", None)
        other_path = outputs(workspace, "other-path-control")
        for project in (workspace / "edit").glob("P*"):
            shutil.rmtree(project / "bin/Release", ignore_errors=True)
            shutil.rmtree(project / "obj/Release", ignore_errors=True)
        empty_cache = workspace / "empty-cache"
        empty_cache.mkdir()
        results["edit-control"] = run(workspace, "edit-control", args.endpoint, source_name="edit", read_cache=str(empty_cache))
        if (results["base"]["hits"], results["base"]["misses"]) != (0, 3):
            raise AssertionError(results["base"])
        if (results["edit"]["hits"], results["edit"]["misses"]) != (2, 1):
            raise AssertionError(results["edit"])
        if (results["recovered"]["hits"], results["recovered"]["misses"]) != (3, 0):
            raise AssertionError(results["recovered"])
        if (results["edit-control"]["hits"], results["edit-control"]["misses"]) != (0, 3):
            raise AssertionError(results["edit-control"])
        if results["edit-control"]["remotePublished"] != 0:
            raise AssertionError("Rebuilding the same fingerprint published a new remote snapshot")
        control = outputs(workspace, "edit-control", source_name="edit")
        if edited != control:
            raise AssertionError({key: (edited.get(key), control.get(key)) for key in edited.keys() | control.keys() if edited.get(key) != control.get(key)})
        if edited != recovered:
            raise AssertionError({key: (edited.get(key), recovered.get(key)) for key in edited.keys() | recovered.keys() if edited.get(key) != recovered.get(key)})
        results["crossPathOutputMismatches"] = sorted(key for key in edited.keys() | other_path.keys() if edited.get(key) != other_path.get(key))
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
