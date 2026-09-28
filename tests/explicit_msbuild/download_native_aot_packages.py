"""Fetch the locked Ubuntu ARM64 .deb inputs for Native AOT qualification."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    lock = json.loads(Path(__file__).with_name("native_aot_packages.lock.json").read_text())
    args.directory.mkdir(parents=True, exist_ok=True)
    for package in lock["packages"]:
        destination = args.directory / (package["name"] + ".deb")
        if not destination.exists():
            with urlopen(package["url"], timeout=120) as response, destination.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        if digest != package["sha256"]:
            destination.unlink()
            raise ValueError("Unexpected Ubuntu package SHA-256 for " + package["name"] + ": " + digest)
        print(package["name"], destination.stat().st_size)


if __name__ == "__main__":
    main()
