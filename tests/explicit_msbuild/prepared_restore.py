"""Check that project Restore stays cached through source and reference edits."""

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


root = Path(__file__).resolve().parents[2]
folder = Path(sys.argv[1]).resolve()
workspace = folder / "src"
shutil.copytree(root / "tests/fixtures/explicit_acceptance", workspace, ignore=shutil.ignore_patterns("bazel-*", "bin", "obj"))
module = workspace / "MODULE.bazel"
module.write_text(module.read_text().replace('path = "../../.."', 'path = ' + json.dumps(str(root))))
archive = workspace / "RestoreProbe.1.0.0.nupkg"
with zipfile.ZipFile(archive, "w") as package:
    package.writestr("RestoreProbe.nuspec", '<package><metadata><id>RestoreProbe</id><version>1.0.0</version><authors>fixture</authors><description>fixture</description></metadata></package>')
    package.writestr("build/RestoreProbe.props", '<Project><PropertyGroup><RestoreProbeLoaded>true</RestoreProbeLoaded></PropertyGroup></Project>')
with (workspace / "BUILD.bazel").open("a") as build:
    build.write('load("@rules_msbuild//msbuild:defs.bzl", "msbuild_nuget_package")\n')
    build.write('msbuild_nuget_package(name="restore_probe",package_id="RestoreProbe",version="1.0.0",archive="RestoreProbe.1.0.0.nupkg",archive_sha256=' + json.dumps(hashlib.sha256(archive.read_bytes()).hexdigest()) + ',content_hash=' + json.dumps(base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()) + ',visibility=["//visibility:public"])\n')
project = workspace / "Library/Library.csproj"
project.write_text(project.read_text().replace("</Project>", '<ItemGroup><PackageReference Include="RestoreProbe" Version="1.0.0" /></ItemGroup><Target Name="VerifyRestoredProps" BeforeTargets="CoreCompile"><Error Condition="\'$(RestoreProbeLoaded)\' != \'true\'" Text="Missing restored package props" /></Target></Project>'))
(workspace / "Library/RestoreInput.cs").write_text("// declared Restore source\n")
worker = os.environ.get("RULES_MSBUILD_PREPARED_WORKER") == "1"
worker_attribute = "linux_worker = True, " if worker else ""
for name in ("Library", "App"):
    build = workspace / name / "BUILD.bazel"
    build.write_text(build.read_text().replace("msbuild_library(", "msbuild_library(prepared_restore = True, " + worker_attribute).replace("msbuild_binary(", "msbuild_binary(prepared_restore = True, " + worker_attribute))
library_build = workspace / "Library/BUILD.bazel"
library_build.write_text(library_build.read_text().replace('srcs = ["Value.cs"],', 'srcs = ["Value.cs", "RestoreInput.cs"],\n    restore_source_inputs = ["RestoreInput.cs"],\n    deps = ["//:restore_probe"],\n    build_deps = ["//:restore_probe"],'))

bazel = os.environ["RULES_MSBUILD_BAZEL"]
command = [bazel, "--output_base=" + str(folder / "base"), "--ignore_all_rc_files"]
records = []


def run(case, expected_restores):
    execution = folder / (case + ".execution.json")
    args = command + ["run", "//App", "--disk_cache=" + str(folder / "cache"), "--execution_log_json_file=" + str(execution)]
    if worker:
        args += ["--strategy=MSBuildAssembly=worker", "--strategy=MSBuildRestore=worker", "--worker_max_instances=MSBuildAssembly=1", "--worker_max_instances=MSBuildRestore=1"]
    result = subprocess.run(args, cwd=workspace, text=True, capture_output=True, timeout=240)
    (folder / (case + ".log")).write_text(result.stdout + result.stderr)
    assert result.returncode == 0, (case, (result.stdout + result.stderr)[-6000:])
    rows = []
    text = execution.read_text()
    decoder = json.JSONDecoder()
    while text.strip():
        row, consumed = decoder.raw_decode(text.lstrip())
        text = text.lstrip()[consumed:]
        if row.get("mnemonic") in ("MSBuildRestore", "MSBuildAssembly"):
            rows.append({"mnemonic": row["mnemonic"], "label": row["targetLabel"], "cacheHit": row.get("cacheHit", False)})
    restores = sorted(row["label"] for row in rows if row["mnemonic"] == "MSBuildRestore" and not row["cacheHit"])
    assert restores == expected_restores, (case, restores, rows)
    records.append({"case": case, "actions": rows})
    print(case, restores, flush=True)


try:
    run("baseline", ["//App:App", "//Library:Library"])
    source = workspace / "Library/Value.cs"
    original = source.read_text()
    source.write_text(original + "\npublic static class AddedApi { public static int Value => 1; }\n")
    run("api-edit", [])
    restore_source = workspace / "Library/RestoreInput.cs"
    restore_source.write_text("// changed declared Restore source\n")
    run("restore-source-edit", ["//Library:Library"])
    project.write_text(project.read_text().replace("</Project>", "<PropertyGroup><Version>2.0.0</Version></PropertyGroup></Project>"))
    run("project-edit", ["//App:App", "//Library:Library"])
    subprocess.run(command + ["shutdown"], cwd=workspace, check=True)
    shutil.rmtree(folder / "base")
    relocated = folder / "relocated"
    shutil.copytree(workspace, relocated, ignore=shutil.ignore_patterns("bazel-*", "bin", "obj"))
    workspace = relocated
    run("cache-recovery", [])
    source = workspace / "Library/Value.cs"
    source.write_text(source.read_text() + "\npublic static class AnotherApi { public static int Value => 2; }\n")
    run("relocated-api-edit", [])
finally:
    subprocess.run(command + ["shutdown"], cwd=workspace, check=True)
    (folder / "report.json").write_text(json.dumps(records, indent=2) + "\n")
