"""Framework selection, macro composition and selected action closure."""

load("@rules_testing//lib:analysis_test.bzl", "analysis_test")
load("//msbuild:defs.bzl", "MSBuildAssemblyInfo", "MSBuildProjectInfo", "msbuild_library", "msbuild_project", "msbuild_test_project")
load(":helpers.bzl", "action", "failure_test", "request")

def _selection(env, targets):
    variants = targets.facade[MSBuildProjectInfo].variants
    env.expect.that_collection(variants.keys()).contains_exactly(["netstandard2.0", "netstandard2.1", "net8.0", "net9.0"])
    env.expect.that_collection(targets.facade[DefaultInfo].files.to_list()).contains_exactly([v.runtime for v in variants.values()])
    for key, framework in [("exact", "net8.0"), ("nearest", "net9.0"), ("standard", "netstandard2.1"), ("older", "netstandard2.0"), ("explicit", "netstandard2.0")]:
        target = getattr(targets, key)
        selected = variants[framework]
        info = target[MSBuildAssemblyInfo]
        env.expect.that_collection(info.references.to_list()).contains_exactly([selected.reference])
        env.expect.that_collection(info.runtimes.to_list()).contains_exactly([selected.runtime])
        inputs = action(target, "MSBuildAssembly").inputs.to_list()
        env.expect.that_collection(inputs).contains(selected.reference)
        env.expect.that_collection(inputs).contains_none_of([v.reference for k, v in variants.items() if k != framework])
        env.expect.that_str(request(target)["dependencyFrameworks"][selected.project]).equals(framework)

def _overrides(env, targets):
    for target, expected, configuration, prop in [(targets.base, ["common.cs"], "Release", "common"), (targets.modern, ["common.cs", "modern.cs"], "Debug", "modern")]:
        req = request(target)
        env.expect.that_collection([s["path"].split("/")[-1] for s in req["sources"]]).contains_exactly(expected)
        env.expect.that_str(req["configuration"]).equals(configuration)
        env.expect.that_str(req["properties"]["Flavor"]).equals(prop)
    env.expect.that_collection(request(targets.modern)["defines"]).contains_exactly(["COMMON", "MODERN"])

def _test_variant(env, target):
    env.expect.that_str(request(target, ".launch.json")["testOptions"]["protocol"]).equals("mtp")
    env.expect.that_dict(target[RunEnvironmentInfo].environment).contains_exactly({"MODE": "test"})
    env.expect.that_bool(target[DefaultInfo].files_to_run.executable != None).equals(True)

def facade_tests(name):
    """Declare facade analysis tests.

    Args:
        name: Prefix for fixture and test targets.
    """
    msbuild_project(name = name, project = "Multi.csproj", target_frameworks = ["netstandard2.0", "netstandard2.1", "net8.0", "net9.0"], tags = ["manual"])
    targets = {"facade": ":" + name}
    for key, framework in [("exact", "net8.0"), ("nearest", "net10.0"), ("standard", "net7.0"), ("older", "netstandard2.0"), ("explicit", "net10.0")]:
        target = name + "_" + key
        msbuild_library(name = target, project = key + ".csproj", target_framework = framework, deps = [":" + name + ("_netstandard2_0" if key == "explicit" else "")], tags = ["manual"])
        targets[key] = ":" + target
    analysis_test(name = name + "_selection", targets = targets, impl = _selection)
    native.config_setting(name = name + "_fastbuild", values = {"compilation_mode": "fastbuild"})
    msbuild_project(
        name = name + "_overrides",
        project = "Overrides.csproj",
        target_frameworks = ["netstandard2.1", "net10.0"],
        srcs = select({":" + name + "_fastbuild": ["common.cs"], "//conditions:default": ["other.cs"]}),
        defines = ["COMMON"],
        msbuild_properties = {"Flavor": "common"},
        framework_overrides = {"net10.0": {"srcs": ["modern.cs"], "defines": ["MODERN"], "configuration": "Debug", "msbuild_properties": {"Flavor": "modern"}}},
        tags = ["manual"],
    )
    analysis_test(name = name + "_overrides_test", targets = {"base": ":" + name + "_overrides_netstandard2_1", "modern": ":" + name + "_overrides_net10_0"}, impl = _overrides)
    msbuild_test_project(name = name + "_tests", project = "FacadeTests.csproj", target_frameworks = ["net8.0", "net10.0"], deps = [":" + name], test_protocol = "mtp", env = {"MODE": "test"}, tags = ["manual"])
    analysis_test(name = name + "_test_launcher", target = ":" + name + "_tests_net10_0", impl = _test_variant)
    for suffix, framework in [("incompatible", "netstandard1.0"), ("platform", "net8.0-windows7.0")]:
        subject = name + "_" + suffix
        msbuild_library(name = subject, project = suffix + ".csproj", target_framework = framework, deps = [":" + name], tags = ["manual"])
        failure_test(subject + "_test", ":" + subject, "No supported framework selection")
    msbuild_library(name = name + "_duplicate", project = "Duplicate.csproj", target_framework = "net8.0", deps = [":" + name, ":" + name + "_net8_0"], tags = ["manual"])
    failure_test(name + "_duplicate_test", ":" + name + "_duplicate", "Select exactly one configured compile dependency per project")
