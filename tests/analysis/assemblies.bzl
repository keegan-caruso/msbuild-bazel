"""Compile contracts, runtime closure, action inputs and worker selection."""

load("@rules_testing//lib:analysis_test.bzl", "analysis_test")
load("//msbuild:defs.bzl", "MSBuildAssemblyInfo", "msbuild_assembly", "msbuild_binary", "msbuild_test")
load(":helpers.bzl", "action", "library", "paths", "request")

def _closure(env, targets):
    targets = {k: getattr(targets, k) for k in dir(targets)}
    leaf, middle, root = [targets[k][MSBuildAssemblyInfo] for k in ["leaf", "middle", "root"]]
    env.expect.that_collection(root.references.to_list()).contains_exactly([leaf.reference, middle.reference])
    env.expect.that_collection(root.runtimes.to_list()).contains_exactly([leaf.runtime, middle.runtime])
    compile = action(targets["root"], "MSBuildAssembly")
    env.expect.that_collection(compile.inputs.to_list()).contains_at_least([leaf.reference, middle.reference])
    env.expect.that_collection(compile.inputs.to_list()).contains_none_of([leaf.runtime, middle.runtime])
    env.expect.that_collection(targets["root"][OutputGroupInfo].reference.to_list()).contains_exactly([root.reference])
    env.expect.that_collection(targets["root"][DefaultInfo].files.to_list()).contains_exactly([root.runtime])
    env.expect.that_str(request(targets["root"])["configuration"]).equals("Release")
    env.expect.that_collection(compile.argv).contains_at_least(["build"])
    env.expect.that_dict(compile.env).contains_exactly({"LANG": "en_US.UTF-8"})
    direct = action(targets["direct"], "MSBuildAssembly")
    env.expect.that_collection(direct.inputs.to_list()).contains(middle.reference)
    env.expect.that_collection(direct.inputs.to_list()).not_contains(leaf.reference)

def _worker(env, target):
    compile = action(target, "MSBuildAssembly")
    env.expect.that_collection(compile.argv).contains("--bazel-worker")
    env.expect.that_bool(any([a.startswith("--tool-inputs=") for a in compile.argv])).equals(True)
    env.expect.that_bool(any([p.endswith("fake_sdk.worker-tools.json") for p in paths(compile.inputs)])).equals(True)

def _launch(env, targets):
    targets = {k: getattr(targets, k) for k in dir(targets)}
    for name in ["binary", "test"]:
        target = targets[name]
        data = paths(target[DefaultInfo].default_runfiles.files)
        env.expect.that_collection(data).contains_at_least(["tests/analysis/payload.txt", "tests/analysis/leaf.runtime"])
        env.expect.that_bool(target[DefaultInfo].files_to_run.executable != None).equals(True)
        launch = request(target, ".launch.json")
        env.expect.that_bool(launch["test"]).equals(name == "test")
    test = targets["test"]
    env.expect.that_dict(test[RunEnvironmentInfo].environment).contains_exactly({"MODE": "fixture"})
    env.expect.that_str(request(test, ".launch.json")["testOptions"]["protocol"]).equals("mtp")

def _pair(env, targets):
    targets = {k: getattr(targets, k) for k in dir(targets)}
    contract, implementation, pair = [targets[k][MSBuildAssemblyInfo] for k in ["contract", "implementation", "pair"]]
    env.expect.that_str(pair.output_mode).equals("paired")
    env.expect.that_file(pair.runtime).equals(implementation.runtime)
    env.expect.that_collection(action(targets["pair"], "MSBuildAssemblyPair").inputs.to_list()).contains(contract.reference)
    env.expect.that_collection(action(targets["pair"], "MSBuildAssemblyPair").inputs.to_list()).not_contains(implementation.reference)
    env.expect.that_collection(action(targets["friend"], "MSBuildAssemblyPair").inputs.to_list()).contains(implementation.reference)

def assembly_tests(name):
    """Declare assemblies tests.

    Args:
        name: Prefix for test names.
    """
    library("leaf", data = ["payload.txt"])
    library("middle", deps = [":leaf"])
    library("root", deps = [":middle"], srcs = ["Source.cs"])
    library("direct", deps = [":middle"], transitive_compile_references = False)
    analysis_test(name = name + "_closure", targets = {n: ":" + n for n in ["leaf", "middle", "root", "direct"]}, impl = _closure)
    library("worker", linux_worker = True, allow_remote_execution = True)
    analysis_test(name = name + "_worker", target = ":worker", impl = _worker)
    msbuild_binary(name = "binary", project = "App.csproj", target_framework = "net10.0", deps = [":leaf"], tags = ["manual"])
    msbuild_test(name = "subject_test", project = "Tests.csproj", target_framework = "net10.0", deps = [":leaf"], test_protocol = "mtp", env = {"MODE": "fixture"}, tags = ["manual"])
    analysis_test(name = name + "_launch", targets = {"binary": ":binary", "test": ":subject_test"}, impl = _launch)
    library("contract", assembly_name = "Shared", output_mode = "reference")
    library("implementation", assembly_name = "Shared", output_mode = "implementation")
    for pair in ["pair", "friend"]:
        msbuild_assembly(name = pair, contract = ":contract", implementation = ":implementation", use_implementation_reference = pair == "friend", tags = ["manual"])
    analysis_test(name = name + "_pair", targets = {n: ":" + n for n in ["contract", "implementation", "pair", "friend"]}, impl = _pair)
