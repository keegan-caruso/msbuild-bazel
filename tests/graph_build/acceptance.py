"""Run the small graph acceptance slices, keeping logs outside the repository."""
import argparse
import os
import platform
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SLICES = ["qualify", "replay", "reviewed_dependencies", "source_groups", "output_ownership", "signing", "package_sdks", "quickstart", "tools", "native_tools", "protocols"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--linux-workers", action="store_true", default=os.environ.get("RULES_MSBUILD_GRAPH_WORKER") == "1", help="include qualified Linux ARM64 workers on both Bazel baselines")
    args = parser.parse_args()
    if args.linux_workers and (sys.platform != "linux" or platform.machine() != "aarch64"):
        parser.error("worker qualification requires Linux ARM64")
    args.directory.mkdir(parents=True, exist_ok=False)
    for name in SLICES:
        with (args.directory / (name + ".log")).open("w") as log:
            result = subprocess.run([sys.executable, str(ROOT / "tests/graph_build" / (name + ".py"))], cwd=ROOT, env=os.environ, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise SystemExit(f"{name} failed: {args.directory / (name + '.log')}")
        print(f"PASS {name}", flush=True)
    if args.linux_workers:
        for version in ["8.8.0", "9.2.0"]:
            with (args.directory / ("worker-" + version + ".log")).open("w") as log:
                result = subprocess.run([sys.executable, str(ROOT / "tests/graph_build/linux_worker.py"), "--bazel-version", version], cwd=ROOT, env=os.environ, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                raise SystemExit(f"Linux worker {version} failed; see {args.directory}")
            print(f"PASS Linux worker {version}", flush=True)


if __name__ == "__main__":
    main()
