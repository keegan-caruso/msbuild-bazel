"""Analysis contracts for the explicit adapter and package-free graph rules."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("//bazel:graph.bzl", "GraphBundle", "graph_project")
load("//bazel:msbuild.bzl", "MsbuildBundle", "msbuild_project")

def _project_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    actions = analysistest.target_actions(env)
    builds = [a for a in actions if a.mnemonic == "MsbuildProject"]
    asserts.equals(env, 1, len(builds))
    build = builds[0]
    inputs = [f.basename for f in build.inputs.to_list()]
    name = target.label.name
    asserts.equals(env, sorted([name + ".bundle", name + ".diagnostics"]), sorted([f.basename for f in build.outputs.to_list()]))
    asserts.equals(env, sorted([name + ".bundle", name + ".diagnostics"]), sorted([f.basename for f in target[DefaultInfo].files.to_list()]))
    for required in [name + ".request.json", "runner.dll", "runner.deps.json", "runner.runtimeconfig.json", "plugin.dll", "Action.props", "Action.targets", "host.json", "sdk.txt", "dotnet.sh", "restore.json", name + ".cs"]:
        asserts.true(env, required in inputs, "missing action input: " + required)
    asserts.equals(env, sorted(ctx.attr.bundles), sorted([f for f in inputs if f.endswith(".bundle")]))
    asserts.false(env, any([f.endswith(".diagnostics") for f in inputs]))
    asserts.equals(env, [name + ".cs"], [f for f in inputs if f.endswith(".cs")])
    expected_env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}
    if ctx.attr.explicit:
        expected_env["RULES_MSBUILD_INPUT_FLAVOR"] = "declared"
        asserts.equals(env, name + ".bundle", target[MsbuildBundle].directory.basename)
    else:
        asserts.equals(env, sorted(ctx.attr.bundles + [name + ".bundle"]), sorted([f.basename for f in target[GraphBundle].bundles.to_list()]))
    asserts.equals(env, expected_env, build.env)
    requests = [a for a in actions if a.mnemonic == "FileWrite"]
    asserts.equals(env, 1, len(requests))
    request = json.decode(requests[0].content)
    asserts.equals(env, "11.0.100-test", request["sdk_version"])
    asserts.equals(env, name + ".bundle", request["output"].split("/")[-1])
    asserts.equals(env, name + ".diagnostics", request["diagnostics"].split("/")[-1])
    asserts.true(env, requests[0].outputs.to_list()[0] in build.inputs.to_list())
    asserts.equals(env, "--request", build.argv[-2])
    asserts.equals(env, requests[0].outputs.to_list()[0].path, build.argv[-1])
    if not ctx.attr.explicit:
        asserts.equals(env, sorted(ctx.attr.bundles), sorted([p.split("/")[-1] for p in request["graph_dependencies"]]))
    return analysistest.end(env)

project_test = analysistest.make(_project_test_impl, attrs = {
    "bundles": attr.string_list(),
    "explicit": attr.bool(),
})

def _failure_test_impl(ctx):
    env = analysistest.begin(ctx)
    asserts.expect_failure(env, ctx.attr.message)
    return analysistest.end(env)

failure_test = analysistest.make(_failure_test_impl, expect_failure = True, attrs = {"message": attr.string()})

def core_suite(name):
    """Declare isolated rule subjects and their tests.

    Args:
      name: Name of the aggregate test suite.
    """
    settings = dict(
        plugin = "plugin.dll",
        build_props = "Action.props",
        build_targets = "Action.targets",
        runner = "runner.dll",
        runner_support = ["runner.deps.json", "runner.runtimeconfig.json"],
        sdk = ":sdk",
        sdk_version = "11.0.100-test",
        dotnet = "dotnet.sh",
        host_identity = "host.json",
        restore = ["restore.json"],
        tags = ["manual"],
    )
    tests = []
    for node, deps in [("shared", []), ("left", ["shared"]), ("right", ["shared"]), ("app", ["left", "right"]), ("unrelated", [])]:
        graph_project(name = node, project = node + ".csproj", srcs = [node + ".cs"], dependencies = [":" + dep for dep in deps], **settings)
        bundles = deps + (["shared"] if node == "app" else [])
        project_test(name = node + "_test", target_under_test = ":" + node, bundles = [dep + ".bundle" for dep in bundles])
        tests.append(node + "_test")
    for node, dependency in [("explicit_shared", None), ("explicit_app", ":explicit_shared")]:
        msbuild_project(name = node, project = "Shared" if not dependency else "App", srcs = [node + ".cs"], dependency = dependency, build_environment = {"RULES_MSBUILD_INPUT_FLAVOR": "declared"}, **settings)
        project_test(name = node + "_test", target_under_test = ":" + node, explicit = True, bundles = ["explicit_shared.bundle"] if dependency else [])
        tests.append(node + "_test")
    msbuild_project(name = "bad_environment", project = "Shared", build_environment = {"PATH": "ambient"}, **settings)
    failure_test(name = "environment_test", target_under_test = ":bad_environment", message = "build_environment keys must start with RULES_MSBUILD_INPUT_")
    graph_project(name = "bad_graph_provider", project = "App.csproj", dependencies = [":sdk"], **settings)
    failure_test(name = "graph_provider_test", target_under_test = ":bad_graph_provider", message = "does not have mandatory providers")
    msbuild_project(name = "bad_explicit_provider", project = "App", dependency = ":sdk", **settings)
    failure_test(name = "explicit_provider_test", target_under_test = ":bad_explicit_provider", message = "does not have mandatory providers")
    native.test_suite(name = name, tests = tests + ["environment_test", "graph_provider_test", "explicit_provider_test"])
