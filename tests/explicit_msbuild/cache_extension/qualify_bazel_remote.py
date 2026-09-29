"""Check project-cache reuse between independent Bazel graph actions."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from qualify import workspace_files


ROOT = Path(__file__).resolve().parents[3]
DOTNET = Path(os.environ.get("RULES_MSBUILD_DOTNET_ROOT", ROOT / ".tools/dotnet")) / "dotnet"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("endpoint", help="Bazel HTTP cache URL")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="rules-msbuild-bazel-remote-") as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        workspace.mkdir()
        workspace_files(workspace, 3)
        salt = uuid.uuid4().hex
        for variant in ("Base", "Body"):
            for project in (workspace / variant).glob("*/*.csproj"):
                project.write_text(project.read_text().replace(
                    "</PropertyGroup>", f"<RemoteQualificationSalt>{salt}</RemoteQualificationSalt></PropertyGroup>",
                ))
        with (workspace / "BUILD.bazel").open("a") as build:
            for name, variant, url in (("remote_base", "Base", args.endpoint), ("remote_body", "Body", args.endpoint), ("body_control", "Body", "")):
                build.write(
                    f'graph_group(name="{name}",srcs=glob(["{variant}/**/*.csproj","{variant}/**/*.cs"]),'
                    f'source_root="{variant}",entry="P2/P2.csproj",'
                    f'dotnet="@dotnet//:dotnet",sdk="@dotnet//:files",probe=":probe",'
                    f'global_json="global.json",cache_url={json.dumps(url)})\n'
                )
        command = [
            str(ROOT / "scripts/bazel-launcher.sh"),
            f"--output_base={root / 'output-base'}",
            "build", "--jobs=2", "--remote_cache=",
            "--strategy=MSBuildCacheGraphGroup=local",
        ]
        reports = {}
        for name in ("remote_base", "remote_body", "body_control"):
            result = subprocess.run(command + ["//:" + name], cwd=workspace, env=os.environ, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f"{name} Bazel build failed:\n{result.stdout}\n{result.stderr}")
            reports[name] = json.loads((workspace / "bazel-bin" / f"{name}.group/cache/report.json").read_text())
            app = workspace / "bazel-bin" / f"{name}.group/workspace/P2/bin/Release/net10.0/P2.dll"
            execution = subprocess.run([str(DOTNET), "exec", str(app)], capture_output=True, text=True)
            if execution.returncode or execution.stdout.strip() != ("1" if name == "remote_base" else "2"):
                raise AssertionError((name, execution.returncode, execution.stdout, execution.stderr))
        if (reports["remote_base"]["hits"], reports["remote_base"]["misses"]) != (0, 3):
            raise AssertionError(reports["remote_base"])
        if (reports["remote_body"]["hits"], reports["remote_body"]["misses"]) != (2, 1):
            raise AssertionError(reports["remote_body"])
        if (reports["body_control"]["hits"], reports["body_control"]["misses"]) != (0, 3):
            raise AssertionError(reports["body_control"])
        for project in ("P0", "P1", "P2"):
            relative = f"{project}/{project}.csproj.cache/manifest.json"
            cached = workspace / "bazel-bin" / "remote_body.group/cache" / relative
            control = workspace / "bazel-bin" / "body_control.group/cache" / relative
            if json.loads(cached.read_text())["Files"] != json.loads(control.read_text())["Files"]:
                raise AssertionError(f"Owned outputs differ for {project}")
        print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
