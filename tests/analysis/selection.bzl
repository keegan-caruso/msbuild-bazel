"""Configured assembly choices preserve explicit compiler and runtime inputs."""

load("@rules_testing//lib:analysis_test.bzl", "analysis_test")
load("//msbuild:defs.bzl", "MSBuildAssemblyInfo", "msbuild_assembly", "msbuild_binary", "msbuild_library")
load(":helpers.bzl", "action", "failure_test", "request")

def _selected(env, targets):
    env.expect.that_collection(targets.outer[MSBuildAssemblyInfo].selections.to_list()).contains_exactly(targets.root[MSBuildAssemblyInfo].selections.to_list())
    modern = targets.modern[MSBuildAssemblyInfo]
    standard = targets.standard[MSBuildAssemblyInfo]
    helper = targets.helper[MSBuildAssemblyInfo]
    root = targets.root[MSBuildAssemblyInfo]
    env.expect.that_collection(root.references.to_list()).contains_exactly([modern.reference, helper.reference])
    env.expect.that_collection(root.runtimes.to_list()).contains_exactly([modern.runtime, helper.runtime])
    env.expect.that_collection(action(targets.root, "MSBuildAssembly").inputs.to_list()).contains_at_least([modern.identity, standard.identity])
    env.expect.that_collection(action(targets.root, "MSBuildAssembly").inputs.to_list()).not_contains(standard.reference)
    env.expect.that_bool(len(request(targets.root)["assemblySelections"]) == 2).equals(True)
    env.expect.that_bool(targets.flavor[MSBuildAssemblyInfo].restore_key == modern.restore_key).equals(False)

def _private(env, targets):
    hidden = targets.hidden[MSBuildAssemblyInfo]
    middle = targets.middle[MSBuildAssemblyInfo]
    env.expect.that_collection(middle.references.to_list()).contains_exactly([])
    env.expect.that_collection(middle.runtimes.to_list()).contains_exactly([hidden.runtime])
    env.expect.that_collection(action(targets.middle, "MSBuildAssembly").inputs.to_list()).contains(hidden.reference)
    env.expect.that_collection(request(targets.outer)["references"]).not_contains(hidden.reference.path)
    env.expect.that_collection(request(targets.outer)["runtimeReferences"]).contains(hidden.reference.path)

def selection_tests(name):
    """Declare configured diamond contracts.

    Args:
        name: Test target prefix.
    """
    for suffix, framework, properties in [("modern", "net10.0", {}), ("standard", "netstandard2.1", {}), ("flavor", "net10.0", {"Flavor": "alternate"})]:
        msbuild_library(name = name + "_" + suffix, project = "Core.csproj", target_framework = framework, msbuild_properties = properties, tags = ["manual"])
    msbuild_library(name = name + "_helper", project = "Helper.csproj", target_framework = "netstandard2.1", deps = [":" + name + "_standard"], tags = ["manual"])
    msbuild_library(name = name + "_root", project = "Root.csproj", target_framework = "net10.0", deps = [":" + name + "_modern", ":" + name + "_helper"], assembly_selections = [":" + name + "_modern"], tags = ["manual"])
    msbuild_library(name = name + "_outer", project = "Outer.csproj", target_framework = "net10.0", deps = [":" + name + "_root"], tags = ["manual"])
    analysis_test(name = name + "_closure", targets = {key: ":" + name + "_" + key for key in ["modern", "standard", "flavor", "helper", "root", "outer"]}, impl = _selected)
    for suffix, selected, message in [("direct", "standard", "Assembly selection disagrees with a direct dependency"), ("absent", "flavor", "Selected implementation is not in the active runtime closure")]:
        msbuild_library(name = name + "_" + suffix, project = "Root.csproj", target_framework = "net10.0", deps = ([":" + name + "_modern"] if suffix == "direct" else []) + [":" + name + "_helper"], assembly_selections = [":" + name + "_" + selected], tags = ["manual"])
        failure_test(name + "_" + suffix + "_test", ":" + name + "_" + suffix, message)
    msbuild_library(name = name + "_standard_choice", project = "Helper.csproj", target_framework = "netstandard2.1", deps = [":" + name + "_standard"], assembly_selections = [":" + name + "_standard"], tags = ["manual"])
    msbuild_library(name = name + "_conflict", project = "Outer.csproj", target_framework = "net10.0", deps = [":" + name + "_root", ":" + name + "_standard_choice"], tags = ["manual"])
    failure_test(name + "_conflict_test", ":" + name + "_conflict", "Conflicting inherited assembly selections")
    msbuild_library(name = name + "_private", project = "Helper.csproj", target_framework = "net10.0", implementation_deps = [":" + name + "_modern"], tags = ["manual"])
    msbuild_binary(name = name + "_private_outer", project = "Outer.csproj", target_framework = "net10.0", deps = [":" + name + "_private"], tags = ["manual"])
    analysis_test(name = name + "_private_inputs", targets = {"hidden": ":" + name + "_modern", "middle": ":" + name + "_private", "outer": ":" + name + "_private_outer"}, impl = _private)

    msbuild_library(name = name + "_contract_dep", project = "Root.csproj", assembly_name = "Core", target_framework = "net10.0", output_mode = "reference", tags = ["manual"])
    msbuild_library(name = name + "_contract", project = "Outer.csproj", assembly_name = "Helper", target_framework = "net10.0", output_mode = "reference", deps = [":" + name + "_contract_dep"], tags = ["manual"])
    msbuild_assembly(name = name + "_pair", contract = ":" + name + "_contract", implementation = ":" + name + "_private", tags = ["manual"])
    msbuild_binary(name = name + "_paired_consumer", project = "Outer.csproj", target_framework = "net10.0", deps = [":" + name + "_pair"], assembly_selections = [":" + name + "_modern"], tags = ["manual"])
    analysis_test(name = name + "_paired_contract_selection", targets = {"consumer": ":" + name + "_paired_consumer", "selected": ":" + name + "_modern", "contract": ":" + name + "_contract_dep"}, impl = _paired)
    msbuild_library(name = name + "_unrelated", project = "Root.csproj", assembly_name = "Core", target_framework = "net10.0", tags = ["manual"])
    msbuild_library(name = name + "_unrelated_helper", project = "Helper.csproj", target_framework = "net10.0", deps = [":" + name + "_unrelated"], tags = ["manual"])
    msbuild_library(name = name + "_unrelated_consumer", project = "Outer.csproj", target_framework = "net10.0", deps = [":" + name + "_modern", ":" + name + "_unrelated_helper"], assembly_selections = [":" + name + "_modern"], tags = ["manual"])
    failure_test(name + "_unrelated_test", ":" + name + "_unrelated_consumer", "Assembly selection cannot replace a different project")

def _paired(env, targets):
    selected = targets.selected[MSBuildAssemblyInfo]
    contract = targets.contract[MSBuildAssemblyInfo]
    data = request(targets.consumer)
    env.expect.that_collection(data["runtimeReferences"]).not_contains(contract.reference.path)
    env.expect.that_collection(action(targets.consumer, "MSBuildAssembly").inputs.to_list()).contains_at_least([selected.identity, contract.identity])
    env.expect.that_bool(len(data["assemblySelections"]) == 2).equals(True)
