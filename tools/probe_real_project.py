#!/usr/bin/env python3
"""Acquire pinned Serilog and record an ordinary MSBuild baseline, without Bazel."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time

REVISION = "49b5339ce85385dc52d4d8e8f2b8308becf23506"
REPOSITORY = "https://github.com/serilog/serilog.git"
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="New directory for source, packages, logs and report")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    report = {"repository": REPOSITORY, "revision": REVISION,
              "platform": platform.platform(), "steps": [], "artifacts": {}}

    def run(name, command):
        start = time.monotonic()
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        (output / (name + ".log")).write_text(result.stdout + result.stderr)
        report["steps"].append({"name": name, "command": command,
                                "seconds": round(time.monotonic() - start, 3),
                                "exitCode": result.returncode})
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(name, result.returncode, report["steps"][-1]["seconds"], flush=True)
        if result.returncode:
            raise SystemExit(f"{name} failed; see {output / (name + '.log')}")
        return result.stdout.strip()

    dotnet = ["bash", str(ROOT / "scripts/dotnet.sh")]
    version = run("sdk-version", dotnet + ["--version"])
    if version != "10.0.100":
        raise SystemExit(f"Expected SDK 10.0.100, got {version}")
    run("clone", ["git", "clone", "--no-checkout", REPOSITORY, str(source)])
    run("checkout", ["git", "-C", str(source), "checkout", "--detach", REVISION])
    project = str(source / "test/Serilog.ApprovalTests/Serilog.ApprovalTests.csproj")
    properties = ["-p:Configuration=Release",
                  "-p:RestorePackagesPath=" + str(output / "packages")]
    run("restore", dotnet + ["restore", project] + properties)
    build = dotnet + ["msbuild", project, "-graphBuild", "-t:Build", "-m"] + properties
    run("cold-build", build + ["-bl:" + str(output / "cold.binlog")])
    run("incremental-build", build + ["-bl:" + str(output / "incremental.binlog")])
    run("approval-test", dotnet + ["test", project, "--no-build", "--no-restore",
                                   "--logger", "trx", "--results-directory",
                                   str(output / "test-results")] + properties)
    for directory in ["src/Serilog", "test/Serilog.ApprovalTests"]:
        for file in sorted((source / directory / "bin/Release").rglob("*")):
            if file.is_file():
                report["artifacts"][str(file.relative_to(source))] = {
                    "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                    "bytes": file.stat().st_size,
                    "executable": bool(file.stat().st_mode & 0o111)}
    report["trackedSourceDiff"] = run("source-diff", ["git", "-C", str(source), "diff", "--stat"])
    report["ok"] = True
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
