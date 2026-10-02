"""Measure leaf, intermediate, and shared Orchard API edits on one Bazel graph.

The source checkout must be the pinned, already prepared generated Orchard graph.
The driver restores every edited file and records actual compilation actions and
reference hashes; it does not infer either from elapsed time.
"""

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import time


CASES = {
    "leaf": ("src/OrchardCore/OrchardCore.Logging.NLog/TenantLayoutRenderer.cs", "src/OrchardCore/OrchardCore.Logging.NLog/OrchardCore.Logging.NLog.csproj"),
    "middle": ("src/OrchardCore/OrchardCore.Infrastructure/PhoneFormatValidator.cs", "src/OrchardCore/OrchardCore.Infrastructure/OrchardCore.Infrastructure.csproj"),
    "shared": ("src/OrchardCore/OrchardCore.Abstractions/Extensions/Manifests/NotFoundManifestInfo.cs", "src/OrchardCore/OrchardCore.Abstractions/OrchardCore.Abstractions.csproj"),
}
TARGET = "//:src_OrchardCore.Cms.Web_OrchardCore.Cms.Web"


def actions(path):
    decoder = json.JSONDecoder()
    contents = path.read_text() if path.exists() else ""
    offset = 0
    while offset < len(contents):
        if contents[offset].isspace():
            offset += 1
            continue
        value, offset = decoder.raw_decode(contents, offset)
        yield value


def references(workspace):
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (workspace / "bazel-bin").glob("*.reference/*.dll")
    }


def dependency_reach(workspace):
    reverse = defaultdict(set)
    for path in (workspace / "bazel-bin").glob("*.request.json"):
        request = json.loads(path.read_text())
        project = request["project"]["path"]
        for dependency in request["dependencies"]:
            reverse[dependency].add(project)
    result = {}
    for case, (_, project) in CASES.items():
        visited = set()
        pending = [project]
        while pending:
            for dependent in reverse[pending.pop()]:
                if dependent not in visited:
                    visited.add(dependent)
                    pending.append(dependent)
        result[case] = {"project": project, "directConsumers": len(reverse[project]), "reachableConsumers": len(visited)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--sample-offset", type=int, default=0)
    parser.add_argument("--disk-cache", type=Path)
    parser.add_argument("--output-base", type=Path)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--worker-memory-limit-mb", type=int, default=4096)
    parser.add_argument("--allow-profiled", action="store_true", help="Permit opt-in compile profiling, which changes elapsed time")
    args = parser.parse_args()
    if min(args.repetitions, args.jobs, args.workers, args.worker_memory_limit_mb) < 1:
        parser.error("repetitions, jobs, workers and worker memory limit must be positive")
    if args.sample_offset < 0:
        parser.error("sample offset must be nonnegative")
    workspace = args.workspace.resolve()
    output = args.output.resolve()
    mapping = json.loads((workspace / "sync.json").read_text())
    defaults = mapping.get("projectDefaults", {})
    profiled = [project for project, binding in mapping["projects"].items() if binding.get("profileBuild", defaults.get("profileBuild", False))]
    if profiled and not args.allow_profiled:
        parser.error(f"{len(profiled)} projects enable profileBuild; disable it for elapsed-time comparisons or pass --allow-profiled for diagnostics")
    output.mkdir(parents=True, exist_ok=False)
    originals = {case: (workspace / source).read_bytes() for case, (source, _) in CASES.items()}
    bazel = [os.environ["RULES_MSBUILD_BAZEL"], "--host_jvm_args=-Xmx1536m", "--ignore_all_rc_files"]
    if args.output_base:
        bazel.append("--output_base=" + str(args.output_base.resolve()))
    flags = [
        "--jobs=" + str(args.jobs), "--worker_max_instances=MSBuildAssembly=" + str(args.workers),
        "--experimental_total_worker_memory_limit_mb=" + str(args.worker_memory_limit_mb), "--experimental_shrink_worker_pool",
        "--disk_cache=" + str((args.disk_cache or output / "cache").resolve()), "--remote_cache=", "--remote_download_outputs=all",
        "--noshow_progress", "--color=no", "--curses=no",
    ]
    report = {"cases": args.cases, "repetitions": args.repetitions, "profiledProjects": len(profiled), "jobs": args.jobs, "workers": args.workers, "workerMemoryLimitMb": args.worker_memory_limit_mb, "sourceHashes": {case: hashlib.sha256(data).hexdigest() for case, data in originals.items()}, "records": []}

    def run(name):
        execution = output / (name + ".execution.json")
        command = bazel + ["build", TARGET, *flags, "--execution_log_json_file=" + str(execution), "--profile=" + str(output / (name + ".profile.gz"))]
        began = time.monotonic()
        with (output / (name + ".log")).open("w") as log:
            result = subprocess.run(command, cwd=workspace, stdout=log, stderr=subprocess.STDOUT)
        action_rows = [action for action in actions(execution) if action.get("mnemonic") == "MSBuildAssembly"]
        executed = [action for action in action_rows if not action.get("cacheHit")]
        compiled = sorted({action["targetLabel"].split(":")[-1] for action in executed})
        row = {"case": name, "seconds": round(time.monotonic() - began, 3), "exitCode": result.returncode, "compiled": compiled, "cacheHits": len(action_rows) - len(executed), "cumulativeActionSeconds": round(sum(float(action.get("metrics", {}).get("totalTime", "0s").removesuffix("s")) for action in executed), 3), "references": references(workspace) if result.returncode == 0 else {}}
        profiles = []
        for target in compiled:
            path = workspace / "bazel-bin" / (target + ".diagnostics") / "worker.json"
            if path.exists():
                profiles.append(json.loads(path.read_text()))
        if profiles:
            phases = ["childSeconds", "stagingSeconds", "identitySeconds", "snapshotSeconds", "preparationSeconds", "publicationSeconds", "snapshotFileSeconds"]
            row["workerSeconds"] = {phase: round(sum(profile.get(phase, 0) for profile in profiles), 3) for phase in phases}
            row["medianChildSeconds"] = round(statistics.median(profile["childSeconds"] for profile in profiles), 3)
        report["records"].append(row)
        (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
        print(name, row["seconds"], "compilations", len(compiled), "exit", result.returncode, flush=True)
        if result.returncode:
            raise RuntimeError("Build failed: " + str(output / (name + ".log")))
        return row

    try:
        baseline = run("baseline")
        report["graph"] = dependency_reach(workspace)
        (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
        for sample in range(args.sample_offset, args.sample_offset + args.repetitions):
            for case in args.cases:
                path = workspace / CASES[case][0]
                suffix = f"\npublic class RulesMsbuildApiEdit{case.title()}{sample} {{ }}\n".encode()
                path.write_bytes(originals[case] + suffix)
                edited = run(f"{case}-{sample}")
                edited["changedReferences"] = sorted(name for name, digest in baseline["references"].items() if edited["references"].get(name) != digest)
                (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
                path.write_bytes(originals[case])
                reverted = run(f"{case}-{sample}-revert")
                reverted["referenceHashesRestored"] = reverted["references"] == baseline["references"]
                (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
                if not reverted["referenceHashesRestored"]:
                    raise RuntimeError("Reverted reference outputs differ from the baseline")
    finally:
        for case, (source, _) in CASES.items():
            (workspace / source).write_bytes(originals[case])
        subprocess.run(bazel + ["shutdown"], cwd=workspace, check=False)


if __name__ == "__main__":
    main()
