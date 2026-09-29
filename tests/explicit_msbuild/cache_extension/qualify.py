"""Generate small and wider graph-cache fixtures and run them as Bazel actions."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DOTNET = Path(os.environ.get("RULES_MSBUILD_DOTNET_ROOT", ROOT / ".tools/dotnet")) / "dotnet"


def graph(workspace: Path, variant: str, count: int) -> None:
    for index in range(count):
        name = f"P{index}"
        folder = workspace / variant / name
        folder.mkdir(parents=True)
        reference = (
            f'<ItemGroup><ProjectReference Include="../P{index - 1}/P{index - 1}.csproj" /></ItemGroup>'
            if index else ""
        )
        output = "<OutputType>Exe</OutputType>" if index == count - 1 else ""
        (folder / f"{name}.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            f"<TargetFramework>net10.0</TargetFramework>{output}"
            "</PropertyGroup>"
            f"{reference}</Project>\n"
        )
        if index == count - 1:
            body = f'System.Console.WriteLine(P{index - 1}.Value.Get());\n'
            (folder / "Program.cs").write_text(body)
        else:
            value = (
                "2" if variant == "Body" and index == 0
                else "1" if index == 0
                else f"P{index - 1}.Value.Get()"
            )
            extra = " public static int Added() => 9;" if variant == "Api" and index == 0 else ""
            (folder / "Value.cs").write_text(
                f"namespace P{index}; public static class Value "
                f"{{ public static int Get() => {value};{extra} }}\n"
            )


def workspace_files(workspace: Path, count: int) -> None:
    system = {"Darwin": "osx", "Linux": "linux"}[platform.system()]
    cpu = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64"}[platform.machine()]
    (workspace / "MODULE.bazel").write_text(
        'module(name="cache_graph_probe")\n'
        'bazel_dep(name="rules_msbuild",version="0.0.0")\n'
        f'local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})\n'
        'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
        f'dotnet.sdk(name="dotnet",version="10.0.400",platforms={json.dumps([system + "-" + cpu])})\n'
        'use_repo(dotnet,"dotnet")\n'
    )
    shutil.copy2(ROOT / "global.json", workspace / "global.json")
    (workspace / ".bazelversion").write_text("9.2.0\n")
    lines = [
        'load("@rules_msbuild//tests/explicit_msbuild/cache_extension:graph_probe.bzl", "probe_binary", "graph_group")',
        'probe_binary(name="probe",dotnet="@dotnet//:dotnet",sdk="@dotnet//:files",',
        '  project="@rules_msbuild//tests/explicit_msbuild/cache_extension:CacheProbe.csproj",',
        '  sources="@rules_msbuild//tests/explicit_msbuild/cache_extension:sources")',
    ]
    for name, variant, seed in [
        ("seed", "Base", None),
        ("body_no_cache", "Body", None),
        ("body", "Body", ":seed"),
        ("api_no_cache", "Api", None),
        ("api", "Api", ":seed"),
    ]:
        lines.extend([
            f'graph_group(name="{name}",srcs=glob(["{variant}/**/*.csproj","{variant}/**/*.cs"]),',
            f'  source_root="{variant}",entry="P{count - 1}/P{count - 1}.csproj",',
            '  dotnet="@dotnet//:dotnet",sdk="@dotnet//:files",probe=":probe",global_json="global.json",',
            f'  seed={json.dumps(seed) if seed else "None"})',
        ])
    (workspace / "BUILD.bazel").write_text("\n".join(lines) + "\n")
    for variant in ("Base", "Body", "Api"):
        graph(workspace, variant, count)


def raw_compare(workspace: Path, count: int) -> dict:
    raw = workspace / "raw"
    shutil.copytree(workspace / "Base", raw / "graph")
    shutil.copy2(workspace / "global.json", raw / "global.json")
    (raw / "empty").mkdir()
    project = raw / "graph" / f"P{count - 1}" / f"P{count - 1}.csproj"
    flags = [
        "-c", "Release", "-m:2", "-p:DisableTransitiveProjectReferences=true",
        "-p:Deterministic=true", f"-p:PathMap={raw / 'graph'}=/_/workspace",
        "-p:UseSharedCompilation=false", "-p:NuGetAudit=false",
    ]

    def build(label: str, arguments: list[str]) -> float:
        started = time.perf_counter()
        result = subprocess.run([str(DOTNET), *arguments], cwd=raw, text=True, capture_output=True)
        elapsed = time.perf_counter() - started
        (raw / f"{label}.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f"Raw MSBuild {label} failed; see {raw / (label + '.log')}")
        return elapsed

    build("restore", ["restore", str(project), "--source", str(raw / "empty"), "-p:NuGetAudit=false"])
    initial = build("initial", ["build", str(project), *flags, "--no-restore"])
    source = raw / "graph" / "P0" / "Value.cs"
    original = source.read_text()
    source.write_text((workspace / "Body" / "P0" / "Value.cs").read_text())
    body = build("body", ["build", str(project), *flags, "--no-restore"])
    source.write_text(original)
    build("reset", ["build", str(project), *flags, "--no-restore"])
    source.write_text((workspace / "Api" / "P0" / "Value.cs").read_text())
    api = build("api", ["build", str(project), *flags, "--no-restore"])
    return {"initialSeconds": initial, "bodySeconds": body, "apiSeconds": api}


def run(count: int, output: Path, recover: bool, raw: bool) -> dict:
    workspace = output / f"graph-{count}"
    workspace.mkdir(parents=True)
    workspace_files(workspace, count)
    command = [
        str(ROOT / "scripts/bazel-launcher.sh"),
        f"--output_base={output / ('bazel-' + str(count))}",
        "build", "--jobs=2", f"--execution_log_json_file={workspace / 'execution.json'}",
        f"--disk_cache={output / 'disk-cache'}", "--remote_cache=",
        "//:seed", "//:body_no_cache", "//:body", "//:api_no_cache", "//:api",
    ]
    result = subprocess.run(command, cwd=workspace, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (workspace / "bazel.log").write_text(result.stdout)
    if result.returncode:
        raise RuntimeError(f"Bazel failed for {count} projects; see {workspace / 'bazel.log'}\n{result.stdout[-4000:]}")
    reports = {}
    for name in ("seed", "body_no_cache", "body", "api_no_cache", "api"):
        reports[name] = json.loads((workspace / "bazel-bin" / f"{name}.group" / "cache" / "report.json").read_text())
        if reports[name]["graphNodes"] != count:
            raise AssertionError((name, reports[name]))
    decoder = json.JSONDecoder()
    execution = (workspace / "execution.json").read_text()
    offset = 0
    while offset < len(execution):
        if execution[offset].isspace():
            offset += 1
            continue
        action, offset = decoder.raw_decode(execution, offset)
        if action.get("mnemonic") == "MSBuildCacheGraphGroup":
            name = action["targetLabel"].split(":")[-1]
            reports[name]["bazelActionSeconds"] = float(action.get("metrics", {}).get("totalTime", "0s").removesuffix("s"))
    for name, value in (("seed", "1"), ("body_no_cache", "2"), ("body", "2"), ("api_no_cache", "1"), ("api", "1")):
        binary = workspace / "bazel-bin" / f"{name}.group" / "workspace" / f"P{count - 1}" / "bin" / "Release" / "net10.0" / f"P{count - 1}.dll"
        run_app = subprocess.run([str(DOTNET), "exec", str(binary)], text=True, capture_output=True)
        if run_app.returncode or run_app.stdout.strip() != value:
            raise AssertionError((name, run_app.returncode, run_app.stdout, run_app.stderr))
    if reports["body"]["hits"] != count - 1 or reports["body"]["misses"] != 1:
        raise AssertionError(("body edit", reports["body"]))
    if reports["api"]["hits"] != count - 2 or reports["api"]["misses"] != 2:
        raise AssertionError(("API edit", reports["api"]))
    for cached, control in (("body", "body_no_cache"), ("api", "api_no_cache")):
        if reports[control]["hits"] != 0 or reports[control]["misses"] != count:
            raise AssertionError(("control", reports[control]))
        for index in range(count):
            name = f"P{index}"
            cache_manifest = workspace / "bazel-bin" / f"{cached}.group" / "cache" / name / f"{name}.csproj.cache" / "manifest.json"
            control_manifest = workspace / "bazel-bin" / f"{control}.group" / "cache" / name / f"{name}.csproj.cache" / "manifest.json"
            if json.loads(cache_manifest.read_text())["Files"] != json.loads(control_manifest.read_text())["Files"]:
                raise AssertionError(("owned output mismatch", cached, control, name))
            for relative in (f"bin/Release/net10.0/{name}.dll", f"obj/Release/net10.0/ref/{name}.dll"):
                a = workspace / "bazel-bin" / f"{cached}.group" / "workspace" / name / relative
                b = workspace / "bazel-bin" / f"{control}.group" / "workspace" / name / relative
                if a.exists() != b.exists() or a.exists() and hashlib.sha256(a.read_bytes()).digest() != hashlib.sha256(b.read_bytes()).digest():
                    raise AssertionError(("artifact mismatch", cached, control, name, relative))
    if recover:
        recovered = output / f"graph-{count}-recovered"
        recovered.mkdir()
        workspace_files(recovered, count)
        core = recovered / "Body" / "P0" / "Value.cs"
        core.write_text(core.read_text().replace("Get() => 2", "Get() => 3"))
        recovered_command = [
            str(ROOT / "scripts/bazel-launcher.sh"),
            f"--output_base={output / ('bazel-recovered-' + str(count))}",
            "build", "--jobs=2", f"--execution_log_json_file={recovered / 'execution.json'}",
            f"--disk_cache={output / 'disk-cache'}", "--remote_cache=", "//:seed", "//:body",
        ]
        recovery = subprocess.run(recovered_command, cwd=recovered, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (recovered / "bazel.log").write_text(recovery.stdout)
        if recovery.returncode:
            raise RuntimeError(f"Independent cache recovery failed: {recovered / 'bazel.log'}\n{recovery.stdout[-4000:]}")
        actions = []
        execution = (recovered / "execution.json").read_text()
        offset = 0
        while offset < len(execution):
            if execution[offset].isspace():
                offset += 1
                continue
            action, offset = decoder.raw_decode(execution, offset)
            if action.get("mnemonic") == "MSBuildCacheGraphGroup":
                actions.append(action)
        seed = [action for action in actions if action["targetLabel"].endswith(":seed")]
        if len(seed) != 1 or not seed[0].get("cacheHit"):
            raise AssertionError(("seed did not recover from disk cache", actions))
        replay = json.loads((recovered / "bazel-bin" / "body.group" / "cache" / "report.json").read_text())
        if replay["hits"] != count - 1 or replay["misses"] != 1:
            raise AssertionError(("recovered seed replay", replay))
        binary = recovered / "bazel-bin" / "body.group" / "workspace" / f"P{count - 1}" / "bin" / "Release" / "net10.0" / f"P{count - 1}.dll"
        run_app = subprocess.run([str(DOTNET), "exec", str(binary)], text=True, capture_output=True)
        if run_app.returncode or run_app.stdout.strip() != "3":
            raise AssertionError(("recovered app", run_app.returncode, run_app.stdout, run_app.stderr))
        reports["recovery"] = {"seedDiskCacheHit": True, **replay}
    if raw:
        reports["rawMsbuild"] = raw_compare(workspace, count)
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sizes", type=int, nargs="+", default=[3, 16, 64])
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--raw", action="store_true", help="also time raw incremental MSBuild")
    args = parser.parse_args()
    output = args.output or Path(tempfile.mkdtemp(prefix="msbuild-cache-graph-"))
    output.mkdir(parents=True, exist_ok=True)
    report = {count: run(count, output, args.recover, args.raw) for count in args.sizes}
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(output)
    print(json.dumps(report, indent=2))
