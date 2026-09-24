"""First runtime qualification gate: unchanged upstream raw build and smoke test.

Acquisition/restore are setup, not benchmark measurements. This deliberately does
not claim Bazel qualification; later gates must preserve this baseline's inputs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time

COMMIT = "60629d14374c56f1cb51819049ad1fa529307f8d"
PROJECT = "src/libraries/Microsoft.Extensions.Primitives"
SPARSE = ["eng", PROJECT, "src/libraries/Common",
          "src/libraries/System.Private.CoreLib", "src/libraries/System.Runtime.InteropServices",
          "src/libraries/System.Reflection.Metadata", "src/libraries/Microsoft.NETCore.Platforms",
          "src/tools/illink", "src/tasks"]

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output", type=Path, help="New disposable directory")
args = parser.parse_args()
root = args.output.resolve()
root.mkdir(parents=True, exist_ok=False)
source = root / "source"
sdk = Path(os.environ["RULES_MSBUILD_DOTNET_ROOT"]).resolve()
dotnet = sdk / "dotnet"
assert platform.system() == "Linux" and platform.machine() == "aarch64", "Qualified environment is Linux ARM64"
records = []
report = {"commit": COMMIT, "sdk": "10.0.400", "platform": "linux-arm64",
          "gate": "raw-primitives-baseline", "bazelQualified": False, "commands": records}


def run(name, command, cwd=root):
    start = time.monotonic()
    with (root / (name + ".log")).open("w") as log:
        result = subprocess.run([str(x) for x in command], cwd=cwd,
                                stdout=log, stderr=subprocess.STDOUT, timeout=900)
    records.append({"case": name, "exitCode": result.returncode,
                    "seconds": round(time.monotonic() - start, 3)})
    (root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(name, result.returncode, flush=True)
    result.check_returncode()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


run("clone", ["git", "clone", "--depth", "1", "--branch", "v10.0.0",
              "--filter=blob:none", "--sparse", "https://github.com/dotnet/runtime.git", source])
assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip() == COMMIT
run("sparse-init", ["git", "sparse-checkout", "init", "--cone"], source)
run("sparse-inputs", ["git", "sparse-checkout", "set", *SPARSE], source)
assert subprocess.check_output([dotnet, "--version"], cwd=source, text=True).strip() == "10.0.400"
report["upstreamGlobalJson"] = json.loads((source / "global.json").read_text())
properties = {"Configuration": "Release", "TargetFramework": "net10.0",
              "TargetArchitecture": "arm64", "TargetOS": "linux",
              "UseLocalTargetingRuntimePack": "false", "NuGetAudit": "false",
              "NetCoreSdkRoot": str(sdk / "sdk/10.0.400")}
report["properties"] = properties
props = ["-p:" + key + "=" + value for key, value in properties.items()]
outputs = {}
for kind in ["ref", "src"]:
    project = f"{PROJECT}/{kind}/Microsoft.Extensions.Primitives.csproj"
    run(kind + "-build", [dotnet, "build", project, *props,
                         "-bl:" + str(root / (kind + ".binlog"))], source)
    run(kind + "-inventory", [dotnet, "msbuild", project, *props,
        "-getProperty:TargetFramework,AssemblyName,TargetPath,ProjectAssetsFile,NETCoreSdkVersion,MSBuildVersion",
        "-getItem:Compile,ProjectReference,PackageReference"], source)
    inventory = json.loads((root / (kind + "-inventory.log")).read_text())
    (root / (kind + "-inventory.json")).write_text(json.dumps(inventory, indent=2) + "\n")
    outputs[kind] = Path(inventory["Properties"]["TargetPath"])

# Record acquisition separately from the eventual, smaller Bazel action closures.
# Restore visits other target frameworks too; this is not a minimal input list.
archives = {}
for assets_path in (source / "artifacts/obj").rglob("project.assets.json"):
    assets = json.loads(assets_path.read_text())
    for key, library in assets["libraries"].items():
        if library["type"] != "package":
            continue
        name, version = key.lower().split("/")
        for package_root in assets["packageFolders"]:
            archive = Path(package_root) / name / version / f"{name}.{version}.nupkg"
            if archive.exists():
                archives[key] = digest(archive)
                break
        else:
            raise AssertionError("Missing restored archive: " + key)
(root / "restored-package-hashes.json").write_text(json.dumps(archives, indent=2, sort_keys=True) + "\n")
report["restoredPackageArchiveCount"] = len(archives)

# Compile a tiny consumer against the actual upstream contract, then execute it
# with the actual implementation. Neither project nor upstream tests are rewritten.
smoke = root / "smoke"
smoke.mkdir()
(smoke / "Smoke.csproj").write_text('''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup>
  <ItemGroup><Reference Include="Microsoft.Extensions.Primitives" HintPath="$(Contract)" /></ItemGroup>
</Project>''')
(smoke / "Program.cs").write_text('''using System;
using System.IO;
using System.Security.Cryptography;
using Microsoft.Extensions.Primitives;
var values = StringValues.Concat(new StringValues("a"), new StringValues("b"));
if (values.Count != 2 || values[1] != "b") return 1;
if (!new StringSegment("prefix-value", 7, 5).Equals(new StringSegment("value"))) return 2;
var assembly = typeof(StringValues).Assembly;
var hash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(assembly.Location))).ToLowerInvariant();
if (hash != args[0]) return 3;
Console.WriteLine(assembly.FullName);
Console.WriteLine("implementation-sha256=" + hash);
return 0;
''')
run("smoke-compile", [dotnet, "build", smoke / "Smoke.csproj", "-c", "Release",
                      "-p:Contract=" + str(outputs["ref"]), "-p:NuGetAudit=false"])
dest = smoke / "bin/Release/net10.0/Microsoft.Extensions.Primitives.dll"
dest.write_bytes(outputs["src"].read_bytes())
run("smoke-execute", [dotnet, smoke / "bin/Release/net10.0/Smoke.dll", digest(outputs["src"])])
assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=source, text=True).strip()
report["outputs"] = {kind: {"sha256": digest(path), "bytes": path.stat().st_size}
                     for kind, path in outputs.items()}
report["sourceUnchanged"] = True
report["nextGate"] = "Declare the reference assembly and configured linker tool/analyzer closure in Bazel"
(root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
