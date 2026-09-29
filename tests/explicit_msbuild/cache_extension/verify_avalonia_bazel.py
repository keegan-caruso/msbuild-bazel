"""Compare cached Avalonia Bazel groups with clean controls by assembly role."""

import hashlib
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DOTNET = Path(os.environ["RULES_MSBUILD_DOTNET_ROOT"]) / "dotnet"


def verify(workspace: Path, output: Path) -> dict:
    source = ROOT / "tests/explicit_msbuild/avalonia/Inspect.cs.txt"
    inspect = output / "inspect"
    inspect.mkdir(parents=True, exist_ok=True)
    (inspect / "Program.cs").write_text(source.read_text())
    (inspect / "Inspect.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>'
        '<OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
        '</PropertyGroup></Project>'
    )
    subprocess.run([str(DOTNET), "build", str(inspect / "Inspect.csproj"), "-c", "Release"], check=True, capture_output=True)
    program = inspect / "bin/Release/net10.0/Inspect.dll"
    rows = {}

    def assembly(path: Path) -> dict:
        return json.loads(subprocess.check_output([str(DOTNET), str(program), "inspect", str(path)], text=True))

    def xaml_methods(data: dict) -> list[tuple[str, str]]:
        return sorted((kind["name"], method["name"]) for kind in data["types"] for method in kind["methods"]
                      if "!XamlIl" in method["name"] or kind["name"].startswith("CompiledAvaloniaXaml."))

    for case in ("xaml", "body", "api"):
        cached = workspace / "bazel-bin" / f"{case}.group"
        control = workspace / "bazel-bin" / f"{case}_control.group"
        report = json.loads((cached / "report.json").read_text())
        baseline = json.loads((control / "report.json").read_text())
        if report["graphNodes"] != 23 or baseline["graphNodes"] != 23 or baseline["hits"] != 0:
            raise AssertionError((case, "unexpected graph/control", report, baseline))
        results = []
        runtime_dirs = {"cached": [], "control": []}
        producers = {}
        for node in report["nodes"]:
            if node["framework"]:
                project = Path(node["project"])
                producers[(node["framework"], project.stem)] = project.parent
        for role, group in (("cached", cached), ("control", control)):
            for (framework, consumer), folder in producers.items():
                directory = group / "workspace" / folder / "bin" / "Release" / framework
                for (producer_framework, producer_name), producer_folder in producers.items():
                    if producer_framework != framework or consumer == producer_name:
                        continue
                    source_dir = group / "workspace" / producer_folder / "bin" / "Release" / framework
                    for extension in (".dll", ".pdb", ".xml"):
                        copy = directory / f"{producer_name}{extension}"
                        own = source_dir / f"{producer_name}{extension}"
                        if copy.exists() and own.exists() and copy.read_bytes() != own.read_bytes():
                            raise AssertionError((case, role, "stale copy-local assembly", copy))
        for node in report["nodes"]:
            framework = node["framework"]
            if not framework:
                continue
            project = Path(node["project"])
            name = project.stem
            paths = {}
            for role, group in (("cached", cached), ("control", control)):
                directory = group / "workspace" / project.parent
                paths[role] = {
                    "ref": directory / "obj" / "Release" / framework / "ref" / f"{name}.dll",
                    "runtime": directory / "bin" / "Release" / framework / f"{name}.dll",
                }
                runtime_dirs[role].append(paths[role]["runtime"].parent)
            for kind in ("ref", "runtime"):
                if not paths["cached"][kind].exists() or not paths["control"][kind].exists():
                    raise AssertionError((case, node, kind, "missing artifact"))
            reference_equal = paths["cached"]["ref"].read_bytes() == paths["control"]["ref"].read_bytes()
            if not reference_equal:
                raise AssertionError((case, node, "reference mismatch"))
            left = assembly(paths["cached"]["runtime"])
            right = assembly(paths["control"]["runtime"])
            if left["resources"] != right["resources"] or xaml_methods(left) != xaml_methods(right):
                raise AssertionError((case, node, "resource or XAML mismatch"))
            results.append({
                "project": str(project), "framework": framework,
                "referenceSha256": hashlib.sha256(paths["cached"]["ref"].read_bytes()).hexdigest(),
                "implementationBytesEqual": paths["cached"]["runtime"].read_bytes() == paths["control"]["runtime"].read_bytes(),
                "compiledXamlMethods": len(xaml_methods(left)),
            })
        executions = {}
        for role, paths in runtime_dirs.items():
            command = [str(DOTNET), str(program), "run", *(str(path) for path in paths)]
            executions[role] = json.loads(subprocess.check_output(command, text=True))
        if executions["cached"] != executions["control"] or executions["cached"]["count"] != (2 if case == "xaml" else 1):
            raise AssertionError((case, "runtime mismatch", executions))
        rows[case] = {
            "hits": report["hits"], "misses": report["misses"],
            "referenceAssembliesEqual": len(results),
            "implementationAssembliesEqual": sum(result["implementationBytesEqual"] for result in results),
            "compiledXamlMethods": sum(result["compiledXamlMethods"] for result in results),
            "runtime": executions["cached"],
        }
    (output / "verification.json").write_text(json.dumps(rows, indent=2) + "\n")
    return rows


if __name__ == "__main__":
    import sys
    result = verify(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
    for case, row in result.items():
        print(case, row["hits"], row["misses"], row["referenceAssembliesEqual"], row["implementationAssembliesEqual"])
