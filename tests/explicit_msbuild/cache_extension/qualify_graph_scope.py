"""Show which framework outputs classic and static-graph MSBuild build."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path


def qualify(output: Path, package_source: Path) -> None:
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    sdk = Path(os.environ["RULES_MSBUILD_DOTNET_ROOT"])
    packages = Path(os.environ["NUGET_PACKAGES"])
    env = dict(os.environ)
    env.update(DOTNET_ROOT=str(sdk), DOTNET_CLI_TELEMETRY_OPTOUT="1")
    sdk_version = subprocess.check_output([str(sdk / "dotnet"), "--version"], env=env, text=True).strip()

    for mode in ("classic", "graph", "graph-with-set-framework"):
        workspace = output / mode
        app = workspace / "App"
        library = workspace / "Library"
        app.mkdir(parents=True)
        library.mkdir()
        (workspace / "global.json").write_text('{"sdk":{"version":"' + sdk_version + '"}}\n')
        metadata = ' SetTargetFramework="TargetFramework=net8.0"' if mode.endswith("set-framework") else ""
        (app / "App.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework>'
            '</PropertyGroup><ItemGroup><ProjectReference Include="../Library/Library.csproj"'
            + metadata + ' /></ItemGroup></Project>\n'
        )
        (app / "App.cs").write_text("public class App { public Library Value => new(); }\n")
        (library / "Library.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFrameworks>net8.0;net10.0</TargetFrameworks>'
            '</PropertyGroup></Project>\n'
        )
        (library / "Library.cs").write_text("public class Library {}\n")

        def run(name: str, command: list[str]) -> str:
            result = subprocess.run(command, cwd=workspace, env=env, capture_output=True, text=True)
            text = result.stdout + result.stderr
            (workspace / f"{name}.log").write_text(text)
            if result.returncode:
                raise RuntimeError(f"{mode} {name} failed; see {workspace / (name + '.log')}")
            return text

        run("restore", [
            str(sdk / "dotnet"), "restore", str(app / "App.csproj"),
            "--source", str(package_source), "-p:NuGetAudit=false",
            f"-p:RestorePackagesPath={packages}",
        ])
        command = [
            str(sdk / "dotnet"), "build", str(app / "App.csproj"),
            "-f", "net8.0", "-c", "Release", "--no-restore", "-m:2",
            "-clp:PerformanceSummary", f"-p:RestorePackagesPath={packages}",
        ]
        if mode != "classic":
            command.append("-graphBuild")
        log = run("build", command)
        net8 = (library / "bin/Release/net8.0/Library.dll").exists()
        net10 = (library / "bin/Release/net10.0/Library.dll").exists()
        app_exists = (app / "bin/Release/net8.0/App.dll").exists()
        compiler = re.search(r"\bCsc\s+(\d+) calls?", log)
        expected_net10 = mode != "classic"
        if not net8 or net10 != expected_net10 or not app_exists:
            raise AssertionError((mode, net8, net10, app_exists))
        print(f"{mode}: Library net8={net8} net10={net10}; Csc calls={compiler.group(1) if compiler else 'unknown'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new temporary output directory")
    parser.add_argument("package_source", type=Path, help="offline source containing the net8 reference pack")
    args = parser.parse_args()
    qualify(args.output.resolve(), args.package_source.resolve())
