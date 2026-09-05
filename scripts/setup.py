"""Install the checked-in Linux x64 toolchain pins; no global installation."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
pins = json.loads((ROOT / "scripts/toolchains.json").read_text())
assert pins["dotnet"]["version"] == json.loads((ROOT / "global.json").read_text())["sdk"]["version"]
assert pins["bazel"]["version"] == (ROOT / ".bazelversion").read_text().strip()
cache = ROOT / ".cache/downloads"
cache.mkdir(parents=True, exist_ok=True)
(ROOT / ".tools").mkdir(exist_ok=True)

for name, pin in pins.items():
    destination = ROOT / (".tools/dotnet" if name == "dotnet" else ".tools/bin")
    executable = destination / name
    stamp = ROOT / ".tools" / (name + ".sha256")
    if executable.is_file() and stamp.exists() and stamp.read_text().strip() == pin["sha256"]:
        print(f"{name} {pin['version']}: already installed", flush=True)
        continue
    archive = cache / pin["sha256"]
    if not archive.exists():
        partial = archive.with_suffix(".partial")
        subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error",
                        "--retry", "3", "--connect-timeout", "20", "--max-time", "300",
                        pin["url"], "--output", str(partial)], check=True)
        partial.replace(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != pin["sha256"]:
        archive.unlink()
        raise SystemExit(f"Checksum mismatch for {name}; removed download, rerun setup.")
    if name == "dotnet":
        with tempfile.TemporaryDirectory(dir=ROOT / ".tools") as temporary:
            subprocess.run(["tar", "--no-same-owner", "-xzf", str(archive), "-C", temporary], check=True)
            if destination.exists():
                shutil.rmtree(destination)
            shutil.move(temporary, destination)
    else:
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(archive, executable)
        executable.chmod(0o755)
    stamp.write_text(pin["sha256"] + "\n")
    print(f"Installed {name} {pin['version']}", flush=True)
