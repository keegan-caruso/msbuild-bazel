"""Run the small graph acceptance slices, keeping logs outside the repository."""
import argparse
import os
import platform
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SLICES = ["qualify", "design_time", "replay", "reviewed_dependencies", "source_groups", "output_ownership", "payload_concurrency", "shared_payloads", "worker_supervision", "publication_queue", "remote_streaming", "remote", "remote_publication", "signing", "package_sdks", "private_assets", "tools", "native_tools", "protocols", "direct_executable_smoke", "executable_launcher"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--linux-workers", action="store_true", default=os.environ.get("RULES_MSBUILD_GRAPH_WORKER") == "1", help="include qualified Linux ARM64 workers on the supported Bazel baseline")
    args = parser.parse_args()
    if args.linux_workers and (sys.platform != "linux" or platform.machine() != "aarch64"):
        parser.error("worker qualification requires Linux ARM64")
    args.directory.mkdir(parents=True, exist_ok=False)
    # These controls compare cold/warm local caches. Ambient HTTP project
    # recovery can turn their fresh-cache correctness controls into hits.
    local_env = dict(os.environ)
    for key in ("RULES_MSBUILD_PROJECT_CACHE_URL", "RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN", "RULES_MSBUILD_PROJECT_CACHE_READ_ONLY"):
        local_env.pop(key, None)
    slices = [(name, []) for name in SLICES]
    if args.linux_workers:
        slices += [("worker_lifecycle", []), ("worker_preparation", []), ("worker_preparation_zero", ["--cache-mb=0"])]
    for name, options in slices:
        script = "worker_preparation" if name == "worker_preparation_zero" else name
        with (args.directory / (name + ".log")).open("w") as log:
            result = subprocess.run([sys.executable, str(ROOT / "tests/graph_build" / (script + ".py")), *options], cwd=ROOT, env=local_env, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise SystemExit(f"{name} failed: {args.directory / (name + '.log')}")
        print(f"PASS {name}", flush=True)
    for name, target in [("quickstart", "//tests/integration:quickstart")] + ([("workers", "//tests/integration:workers"), ("evaluation_worker", "//tests/integration:evaluation_worker"), ("worker_defaults", "//tests/integration:worker_defaults")] if args.linux_workers else []):
        with (args.directory / (name + ".log")).open("w") as log:
            result = subprocess.run(["bash", str(ROOT / "scripts/bazel.sh"), "test", target, "--test_output=errors"], cwd=ROOT, env=os.environ, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise SystemExit(f"{name} failed; see {args.directory}")
        print(f"PASS native Bazel integration {name}", flush=True)



if __name__ == "__main__":
    main()
