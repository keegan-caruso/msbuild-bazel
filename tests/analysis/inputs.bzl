"""Package, generation, tool and resource input contracts."""

load("@rules_testing//lib:analysis_test.bzl", "analysis_test")
load("//msbuild:defs.bzl", "MSBuildAssemblyInfo", "MSBuildItemsInfo", "MSBuildPackageInfo", "MSBuildRestoreInfo", "msbuild_file_binding", "msbuild_generate", "msbuild_items", "msbuild_nuget_package", "msbuild_package_lock", "msbuild_restore", "msbuild_target_items", "msbuild_tool")
load(":helpers.bzl", "action", "library", "paths", "request")

def _inputs(env, targets):
    targets = {k: getattr(targets, k) for k in dir(targets)}
    target = targets["consumer"]
    inputs = action(target, "MSBuildAssembly").inputs.to_list()
    package = targets["package"][MSBuildPackageInfo]
    env.expect.that_collection(inputs).contains_at_least(package.files.to_list())
    env.expect.that_collection(paths(action(target, "MSBuildAssembly").inputs)).contains_at_least(["tests/analysis/Source.cs", "tests/analysis/resource.txt", "tests/analysis/Custom.targets", "tests/analysis/generated.generated/Generated.cs"])
    env.expect.that_collection(inputs).contains(targets["analyzer"][MSBuildAssemblyInfo].runtime)

    # Tools are in the execution configuration; inspect their paths, not File identity.
    env.expect.that_bool(any([f.short_path == "tests/analysis/task.runtime" for f in inputs])).equals(True)
    env.expect.that_collection(target[MSBuildAssemblyInfo].runtimes.to_list()).contains_none_of([targets["analyzer"][MSBuildAssemblyInfo].runtime])
    row = request(target)
    env.expect.that_collection(row["declaredPackages"]).contains_exactly(["Example"])
    env.expect.that_str(row["fileBindings"][0]["property"]).equals("TaskLocation")
    env.expect.that_str(row["items"][0]["metadata"]["LogicalName"]).equals("message")
    env.expect.that_collection(targets["private"][MSBuildAssemblyInfo].compile_packages.to_list()).contains_exactly([])
    env.expect.that_collection(targets["private"][MSBuildAssemblyInfo].package_files.to_list()).contains(package.directory)
    extract = action(targets["package"], "MSBuildNugetExtract")
    env.expect.that_collection(paths(extract.inputs)).contains("tests/analysis/example.nupkg")
    env.expect.that_collection(extract.argv).contains("extract")

def _generation(env, target):
    env.expect.that_collection(paths(target[DefaultInfo].files)).contains_exactly(["tests/analysis/generated.generated/Generated.cs"])
    env.expect.that_collection(paths(getattr(target[OutputGroupInfo], "Generated.cs"))).contains_exactly(["tests/analysis/generated.generated/Generated.cs"])
    env.expect.that_collection(request(target)["generateTargets"]).contains_exactly(["Generate"])
    env.expect.that_collection(action(target, "MSBuildGenerate").argv).contains("build")

def _restore(env, targets):
    targets = {k: getattr(targets, k) for k in dir(targets)}
    restore = targets["restore"][MSBuildRestoreInfo]
    env.expect.that_str(restore.framework).equals("net10.0")
    env.expect.that_collection(action(targets["restored"], "MSBuildAssembly").inputs.to_list()).contains(restore.file)
    env.expect.that_str(request(targets["restored"])["restoreInput"]).equals(restore.file.path)
    items = targets["target_items"][MSBuildItemsInfo]
    env.expect.that_str(items.target_items[0]["target"]).equals("Export")
    env.expect.that_collection(items.files.to_list()).contains(targets["exporter"][MSBuildAssemblyInfo].target_output)

def input_tests(name):
    """Declare inputs tests.

    Args:
        name: Prefix for test names.
    """
    msbuild_nuget_package(name = "package", package_id = "Example", version = "1.0.0", archive = "example.nupkg", content_hash = "fixture", archive_sha256 = "fixture", tags = ["manual"])
    msbuild_package_lock(name = "lock", packages = [":package"], tags = ["manual"])
    library("analyzer")
    library("task")
    msbuild_tool(name = "tool", assembly = ":task", tags = ["manual"])
    msbuild_file_binding(name = "binding", tool = ":tool", property_name = "TaskLocation", tags = ["manual"])
    msbuild_items(name = "resources", item_type = "EmbeddedResource", srcs = ["resource.txt"], metadata = {"LogicalName": "message"}, tags = ["manual"])
    msbuild_generate(name = "generated", project = "Generate.csproj", target_framework = "net10.0", targets = ["Generate"], outputs = ["Generated.cs"], tags = ["manual"])
    library("consumer", srcs = ["Source.cs", ":generated"], msbuild_imports = ["Custom.targets"], deps = [":package"], package_lock = ":lock", analyzers = [":analyzer"], tools = [":tool"], bindings = [":binding"], items = [":resources"])
    library("private", deps = [":package"], package_private_assets = {"Example": "all"})
    analysis_test(name = name + "_closure", targets = {n: ":" + n for n in ["consumer", "package", "analyzer", "private"]}, impl = _inputs)
    analysis_test(name = name + "_generation", target = ":generated", impl = _generation)
    msbuild_restore(name = "restore", target_framework = "net10.0", tags = ["manual"])
    library("restored", restore = ":restore")
    library("exporter", export_targets = {"Export": ["Compile"]})
    msbuild_target_items(name = "target_items", deps = [":exporter"], target = "Export", item_type = "Compile", tags = ["manual"])
    analysis_test(name = name + "_restore", targets = {n: ":" + n for n in ["restore", "restored", "exporter", "target_items"]}, impl = _restore)
