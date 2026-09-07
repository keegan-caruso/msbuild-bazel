"""R02-R04 semantic contracts for package, configured and test rule subjects."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("//bazel:graph.bzl", "GraphBundle", "graph_project")
load("//bazel:graph_test.bzl", "graph_test")
load(":analysis.bzl", "failure_test")

def _build_contract_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    actions = analysistest.target_actions(env)
    builds = [a for a in actions if a.mnemonic == "MsbuildProject"]
    asserts.equals(env, 1, len(builds))
    build = builds[0]
    inputs = [f.short_path for f in build.inputs.to_list()]
    requests = [a for a in actions if a.mnemonic == "FileWrite"]
    asserts.equals(env, 1, len(requests))
    request = json.decode(requests[0].content)
    asserts.equals(env, ctx.attr.properties, request["graph_global_properties"])
    asserts.equals(env, ctx.attr.project, request["graph_project"])
    asserts.equals(env, ctx.attr.assets or None, request["graph_assets_file"])
    asserts.equals(env, ctx.attr.directories or None, request["graph_output_directories"])
    asserts.equals(env, sorted(ctx.attr.packages), sorted([p["source"] for p in request["packages"]]))
    asserts.equals(env, ctx.attr.manifest or None, request["package_manifest"])
    asserts.equals(env, ctx.attr.restore, request["restore"])
    for path in ctx.attr.packages + ctx.attr.restore + ([ctx.attr.manifest] if ctx.attr.manifest else []):
        asserts.true(env, path in inputs, "missing consumer input: " + path)
    for path in ctx.attr.excluded:
        asserts.false(env, path in inputs, "unrelated package/restore leaked: " + path)
    expected = [name + ".bundle" for name in ctx.attr.bundles]
    asserts.equals(env, sorted(expected), sorted([p.split("/")[-1] for p in request["graph_dependencies"]]))
    asserts.equals(env, sorted(expected + [target.label.name + ".bundle"]), sorted([f.basename for f in target[GraphBundle].bundles.to_list()]))
    asserts.false(env, any([p.endswith(".diagnostics") for p in inputs]))
    asserts.equals(env, [target.label.name + ".bundle", target.label.name + ".diagnostics"], sorted([f.basename for f in build.outputs.to_list()]))
    return analysistest.end(env)

build_contract_test = analysistest.make(_build_contract_impl, attrs = {
    "properties": attr.string_dict(),
    "project": attr.string(),
    "assets": attr.string(),
    "directories": attr.string_list(),
    "packages": attr.string_list(),
    "manifest": attr.string(),
    "restore": attr.string_list(),
    "excluded": attr.string_list(),
    "bundles": attr.string_list(),
})

def _test_contract_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    info = target[DefaultInfo]
    asserts.equals(env, "approval.sh", info.files_to_run.executable.basename)
    paths = [f.short_path for f in info.default_runfiles.files.to_list()]
    for name in ["runner.dll", "runner.deps.json", "runner.runtimeconfig.json", "host.json", "sdk.txt", "dotnet.sh", "approved.txt", "approval.request.json"]:
        asserts.true(env, "tests/starlark/" + name in paths, "missing runfile: " + name)
    asserts.equals(env, ["package_consumer.bundle", "package_producer.bundle"], sorted([p.split("/")[-1] for p in paths if p.endswith(".bundle")]))
    asserts.false(env, any([p.endswith(".diagnostics") or p.endswith(".cs") or p.endswith(".nupkg") for p in paths]))
    asserts.equals(env, {"no-remote": "1"}, target[testing.ExecutionInfo].requirements)
    requests = [a for a in analysistest.target_actions(env) if a.mnemonic == "FileWrite" and a.outputs.to_list()[0].basename.endswith(".json")]
    asserts.equals(env, 1, len(requests))
    request = json.decode(requests[0].content)
    asserts.equals(env, ["Approval.One"], request["expectedTests"])
    asserts.equals(env, "test/Approval.csproj", request["project"])
    asserts.equals(env, {"configuration": "Release", "targetframework": "net10.0"}, request["globalProperties"])
    asserts.equals(env, "test/bin/Release/net10.0", request["runtimeDirectory"])
    asserts.equals(env, "Approval.dll", request["assembly"])
    asserts.equals(env, "/_/workspace", request["sourceRoot"])
    asserts.equals(env, [{"source": ctx.workspace_name + "/tests/starlark/approved.txt", "destination": "tests/starlark/approved.txt", "sha256": "a" * 64}], request["testData"])
    asserts.true(env, request["sdkRoot"].endswith("/tests/starlark"))
    return analysistest.end(env)

test_contract_test = analysistest.make(_test_contract_impl)

def extension_suite(name):
    """Declare nonexecuted analysis subjects and executable assertion tests.

    Args:
      name: Aggregate suite name.
    """
    settings = dict(plugin = "plugin.dll", build_props = "Action.props", build_targets = "Action.targets", runner = "runner.dll", runner_support = ["runner.deps.json", "runner.runtimeconfig.json"], sdk = ":sdk", dotnet = "dotnet.sh", host_identity = "host.json", tags = ["manual"])
    payload = ["package-ref.dll", "package-lib.dll", "package.nupkg"]
    prefix = "tests/starlark/"
    for node, packages, dependencies, restore in [("package_producer", payload, [], "producer-restore.json"), ("package_consumer", [], [":package_producer"], "consumer-restore.json")]:
        manifest = "producer-packages.json" if packages else "consumer-packages.json"
        graph_project(name = node, project = node + ".csproj", srcs = ["app.cs"], restore = [restore], packages = packages, package_manifest = manifest, dependencies = dependencies, **settings)
        build_contract_test(name = node + "_contract", target_under_test = ":" + node, project = node + ".csproj", properties = {"configuration": "Release"}, packages = [prefix + p for p in packages], manifest = prefix + manifest, restore = [prefix + restore], bundles = ["package_producer"] if dependencies else [], excluded = [prefix + "consumer-restore.json"] if packages else [prefix + p for p in payload + ["producer-packages.json", "producer-restore.json"]])
    for flavor in ["red", "blue"]:
        node = "configured_" + flavor
        props = {"configuration": "Release", "targetframework": "net10.0", "flavor": flavor}
        assets = "Shared/obj/" + flavor + "/project.assets.json"
        directories = ["Shared/bin/" + flavor + "/Release/net10.0", "Shared/obj/" + flavor + "/Release/net10.0"]
        graph_project(name = node, project = "Shared/Shared.csproj", srcs = ["shared.cs"], global_properties = props, assets_file = assets, output_directories = directories, restore = ["restore.json"], **settings)
        build_contract_test(name = node + "_contract", target_under_test = ":" + node, project = "Shared/Shared.csproj", properties = props, assets = assets, directories = directories, restore = [prefix + "restore.json"])
    test_settings = dict(subject = ":package_consumer", project = "test/Approval.csproj", global_properties = {"configuration": "Release", "targetframework": "net10.0"}, runtime_directory = "test/bin/Release/net10.0", assembly = "Approval.dll", runner = "runner.dll", runner_support = ["runner.deps.json", "runner.runtimeconfig.json"], host_identity = "host.json", sdk = ":sdk", dotnet = "dotnet.sh", tags = ["manual"])
    graph_test(name = "approval", data = ["approved.txt"], data_hashes = {prefix + "approved.txt": "a" * 64}, expected_tests = ["Approval.One"], **test_settings)
    test_contract_test(name = "approval_contract", target_under_test = ":approval")
    graph_test(name = "missing_hash", data = ["approved.txt"], expected_tests = ["Approval.One"], **test_settings)
    failure_test(name = "missing_hash_contract", target_under_test = ":missing_hash", message = "missing declared test data hash")
    graph_test(name = "empty_tests", expected_tests = [], **test_settings)
    failure_test(name = "empty_tests_contract", target_under_test = ":empty_tests", message = "expected_tests must contain unique nonempty test names")
    graph_test(name = "blank_test", expected_tests = [""], **test_settings)
    failure_test(name = "blank_test_contract", target_under_test = ":blank_test", message = "expected_tests must contain unique nonempty test names")
    graph_test(name = "duplicate_tests", expected_tests = ["Approval.One", "Approval.One"], **test_settings)
    failure_test(name = "duplicate_tests_contract", target_under_test = ":duplicate_tests", message = "expected_tests must contain unique nonempty test names")
    invalid = dict(test_settings)
    invalid["subject"] = ":sdk"
    graph_test(name = "missing_test_provider", expected_tests = ["Approval.One"], **invalid)
    failure_test(name = "missing_test_provider_contract", target_under_test = ":missing_test_provider", message = "does not have mandatory providers")
    native.test_suite(name = name, tests = [":" + subject + "_contract" for subject in ["package_producer", "package_consumer", "configured_red", "configured_blue", "approval", "missing_hash", "empty_tests", "blank_test", "duplicate_tests", "missing_test_provider"]])
