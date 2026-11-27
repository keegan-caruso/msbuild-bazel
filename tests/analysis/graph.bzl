"""Graph inputs, worker defaults, complete layouts and launch contracts."""

load("@rules_testing//lib:analysis_test.bzl", "analysis_test")
load("//msbuild:defs.bzl", "MSBuildLayoutInfo", "MSBuildRuntimeInfo", "MSBuildToolInfo", "msbuild_file_binding", "msbuild_graph", "msbuild_graph_binary", "msbuild_graph_layout", "msbuild_graph_layouts", "msbuild_graph_output", "msbuild_graph_restore", "msbuild_graph_test", "msbuild_layout", "msbuild_nuget_package", "msbuild_package_lock", "msbuild_runtime", "msbuild_runtime_layout", "msbuild_test_tool", "msbuild_tool")
load(":helpers.bzl", "action", "failure_test", "paths", "request")

def _inputs(env, targets):
    build = action(targets.graph, "MSBuildGraph")
    env.expect.that_collection(paths(targets.graph[OutputGroupInfo].runner)).contains_exactly(["tests/analysis/Runner.dll"])
    env.expect.that_collection(paths(build.inputs)).contains_at_least(["tests/analysis/App.csproj", "tests/analysis/Source.cs", "tests/analysis/contract.json", "tests/analysis/sdk.txt"])
    env.expect.that_collection(build.argv).contains("0")

    # Archives are staged by Restore; the validation action must remain required
    # without exposing its expanded package tree as a graph input.
    env.expect.that_collection(paths(build.inputs)).contains_at_least(["tests/analysis/fixture.nupkg", "tests/analysis/package.validated.json"])
    env.expect.that_collection(paths(build.inputs)).not_contains("tests/analysis/package.package")
    env.expect.that_collection(paths(build.inputs)).contains("tests/analysis/tree/bin")
    env.expect.that_str(targets.tool[MSBuildToolInfo].entry_point).equals("Tasks.dll")
    env.expect.that_str(targets.tool[MSBuildToolInfo].directory.short_path).equals(targets.layout[MSBuildLayoutInfo].directory.short_path)

def _worker(env, target):
    env.expect.that_bool(request(target, ".graph-request.json")["profileBuild"]).equals(False)

def _launch(env, targets):
    host = targets.host[MSBuildRuntimeInfo]
    env.expect.that_collection(targets.app[DefaultInfo].default_runfiles.files.to_list()).contains_at_least(host.files.to_list())
    env.expect.that_collection(paths(targets.app[DefaultInfo].default_runfiles.files)).not_contains("tests/analysis/Runner.dll")

def _direct_launch(env, targets):
    host = targets.host[MSBuildRuntimeInfo]
    app = targets.app[DefaultInfo]
    runtime = action(targets.app, "MSBuildGraphRuntime").outputs.to_list()

    # Exact membership rejects helper runtime/support files and launch requests.
    env.expect.that_collection(app.default_runfiles.files.to_list()).contains_exactly(runtime + host.files.to_list() + [app.files_to_run.executable])
    env.expect.that_collection(paths(app.default_runfiles.files)).not_contains("tests/analysis/Runner.dll")
    env.expect.that_collection(paths(app.default_runfiles.files)).not_contains("tests/analysis/dotnet")

def _combined_layout(env, target):
    layout = action(target, "MSBuildGraphLayout")
    env.expect.that_collection(paths(layout.inputs)).contains("tests/analysis/graph.graph")
    env.expect.that_bool(request(target, ".layout.json")["output"].endswith("combined_export.layout")).equals(True)

def _selected_layout(env, target):
    layout = action(target, "MSBuildGraphLayout")
    env.expect.that_bool(any([arg.endswith("tests/analysis/multiple_frameworks.graph/workspace/bin/net10.0") for arg in layout.argv])).equals(True)

def _runtime_layout(env, target):
    layout = action(target, "MSBuildRuntimeLayout")
    env.expect.that_collection(paths(layout.inputs)).contains_at_least(["tests/analysis/framework_graph.graph", "tests/analysis/contract.json", "tests/analysis/dotnet"])
    data = request(target, ".runtime-layout.json")
    env.expect.that_str(data["managed"]["App.dll"]["path"]).equals("bin/Release/net10.0/App.dll")
    env.expect.that_str(data["native"]["dotnet"]["path"]).equals("dotnet")
    env.expect.that_str(data["shared"]).equals("shared/Microsoft.NETCore.App/10.0.0")

def _coverage(env, target):
    env.expect.that_collection(paths(target[InstrumentedFilesInfo].instrumented_files)).contains("tests/analysis/Source.cs")
    data = request(target, ".launch.json")
    env.expect.that_str(data["testOptions"]["coverage"]).equals("coverlet")
    env.expect.that_str(data["testOptions"]["coverageSources"]["tests/analysis/Source.cs"]).equals("tests/analysis/Source.cs")

def graph_tests(name):
    """Declare graph analysis controls.

    Args:
        name: Test prefix.
    """
    common = {"runner": ":runner_payload", "contract": "contract.json", "srcs": ["App.csproj", "Source.cs"], "tags": ["manual"]}
    msbuild_layout(name = "tool_layout", paths = {"Runner.dll": "Tasks.dll"}, tags = ["manual"])
    msbuild_tool(name = "task_tool", layout = ":tool_layout", entry_point = "Tasks.dll", tags = ["manual"])
    msbuild_file_binding(name = "binding", tool = ":task_tool", property_name = "TaskLocation", tags = ["manual"])
    msbuild_nuget_package(name = "package", package_id = "Fixture", version = "1.0.0", archive = "fixture.nupkg", archive_sha256 = "0" * 64, content_hash = "eA==", tags = ["manual"])
    msbuild_package_lock(name = "package_lock", packages = [":package"], tags = ["manual"])
    msbuild_graph_output(name = "tree", graph = ":worker", path = "bin", directory = True, tags = ["manual"])
    msbuild_graph(name = "graph", input_paths = {":tree": "prepared"}, package_lock = ":package_lock", bindings = [":binding"], project_outputs = {"App.csproj|net10.0": ["bin/Release/net10.0", "App.dll", "Exe"]}, **common)
    msbuild_graph(name = "worker", linux_worker = True, linux_stable_paths = True, **common)
    analysis_test(name = name + "_inputs", targets = {"graph": ":graph", "tool": ":task_tool", "layout": ":tool_layout"}, impl = _inputs)
    analysis_test(name = name + "_worker", target = ":worker", impl = _worker)
    msbuild_runtime(name = "source_host", layout = ":tool_layout", entry_point = "corerun", launch_mode = "corerun", tags = ["manual"])
    msbuild_graph_binary(name = "app", graph = ":graph", project = "App.csproj", runtime_host = ":source_host", tags = ["manual"])
    analysis_test(name = name + "_launch", targets = {"host": ":source_host", "app": ":app"}, impl = _launch)
    msbuild_layout(name = "direct_host_layout", paths = {"dotnet": "dotnet"}, tags = ["manual"])
    msbuild_runtime(name = "direct_host", layout = ":direct_host_layout", entry_point = "dotnet", runtime_identifier = "linux-arm64", version = "11.0.0", data = ["payload.txt"], tags = ["manual"])
    msbuild_graph_test(name = "coverage_test", graph = ":graph", project = "App.csproj", test_protocol = "mtp", test_coverage = "coverlet", tags = ["manual"])
    analysis_test(name = name + "_coverage", target = ":coverage_test", impl = _coverage, config_settings = {"//command_line_option:collect_code_coverage": True})
    msbuild_graph_test(name = "direct_smoke", graph = ":graph", project = "App.csproj", runtime_host = ":direct_host", direct_executable_smoke = True, tags = ["manual"])
    analysis_test(name = name + "_direct_launch", targets = {"host": ":direct_host", "app": ":direct_smoke"}, impl = _direct_launch)
    msbuild_graph_test(name = "registered_direct_smoke", graph = ":graph", project = "App.csproj", direct_executable_smoke = True, tags = ["manual"])
    analysis_test(name = name + "_registered_direct_launch", targets = {"host": ":fake_runtime", "app": ":registered_direct_smoke"}, impl = _direct_launch)
    msbuild_graph_test(name = "writable_smoke", graph = ":graph", project = "App.csproj", runtime_host = ":direct_host", tags = ["manual"])
    analysis_test(name = name + "_writable_launch", targets = {"host": ":direct_host", "app": ":writable_smoke"}, impl = _direct_launch)
    msbuild_test_tool(name = "direct_test_tool", package = ":package", path = "Runner.dll", tags = ["manual"])
    msbuild_runtime(name = "direct_env_host", layout = ":direct_host_layout", entry_point = "dotnet", runtime_identifier = "linux-arm64", env = {"CUSTOM_HOST_SETTING": "value"}, tags = ["manual"])
    for case, attrs, message in [
        ("protocol", {"test_protocol": "mtp"}, "direct_executable_smoke requires the executable test protocol"),
        ("exit", {"expected_exit_code": 100}, "direct_executable_smoke requires expected_exit_code = 0"),
        ("settings", {"test_settings": "settings.xml"}, "direct_executable_smoke does not support test_settings"),
        ("settings_output", {"test_settings_output": "generated.xml"}, "direct_executable_smoke does not support test_settings_output"),
        ("filter", {"test_filter_argument": "--filter"}, "direct_executable_smoke does not support test_filter_argument"),
        ("empty", {"allow_empty_tests": True}, "direct_executable_smoke does not support allow_empty_tests"),
        ("output_dirs", {"test_output_dirs": ["results"]}, "direct_executable_smoke does not support test_output_dirs"),
        ("working_directory", {"test_working_directory": "work"}, "direct_executable_smoke does not support test_working_directory"),
        ("data", {"data_paths": {"payload.txt": "payload.txt"}}, "direct_executable_smoke does not support data_paths"),
        ("host", {"runtime_host": ":source_host"}, "direct_executable_smoke requires a dotnet runtime host"),
        ("host_env", {"runtime_host": ":direct_env_host"}, "direct_executable_smoke does not support custom runtime host environment"),
        ("sharding", {"shard_count": 2}, "Executable tests do not yet support sharding"),
        ("diagnostics", {"test_diagnostics": True}, "test_diagnostics currently requires VSTest"),
        ("runner", {"test_runner": ":direct_test_tool"}, "test_runner and test_adapters are only supported by VSTest"),
        ("adapters", {"test_adapters": [":direct_test_tool"]}, "test_runner and test_adapters are only supported by VSTest"),
    ]:
        msbuild_graph_test(name = "invalid_direct_" + case, **dict({"graph": ":graph", "project": "App.csproj", "runtime_host": ":direct_host", "direct_executable_smoke": True, "tags": ["manual"]}, **attrs))
        failure_test(name + "_direct_" + case, ":invalid_direct_" + case, message)
    msbuild_graph_layout(name = "export", graph = ":graph", project = "App.csproj", tags = ["manual"])
    msbuild_graph_layouts(name = "combined_export", graph = ":graph", projects = {"App.csproj|net10.0": "app"}, tags = ["manual"])
    analysis_test(name = name + "_combined_layout", target = ":combined_export", impl = _combined_layout)
    msbuild_graph(name = "framework_graph", project_outputs = {"App.csproj|net10.0": ["bin/Release/net10.0", "App.dll", "Library"]}, **common)
    runtime_attrs = {"graph": ":framework_graph", "projects": ["App.csproj|net10.0"], "native": {"dotnet": "dotnet"}, "version": "10.0.0", "target_framework": "net10.0", "target_framework_moniker": ".NETCoreApp,Version=v10.0", "runtime_identifier": "linux-arm64", "tags": ["manual"]}
    msbuild_runtime_layout(name = "framework_layout", **runtime_attrs)
    analysis_test(name = name + "_runtime_layout", target = ":framework_layout", impl = _runtime_layout)
    for case, attrs, message in [
        ("runtime_missing", {"projects": ["missing|net10.0"]}, "Unknown runtime graph project"),
        ("runtime_duplicate", {"projects": ["App.csproj|net10.0", "App.csproj|net10.0"]}, "Duplicate runtime assembly"),
        ("runtime_escape", {"native": {"dotnet": "../dotnet"}}, "Runtime layout requires a safe"),
    ]:
        msbuild_runtime_layout(name = case, **dict(runtime_attrs, **attrs))
        failure_test(name + "_" + case, ":" + case, message)
    for case, attrs, message in [
        ("layout_empty", {"projects": {}}, "Graph layout batch requires at least one"),
        ("layout_missing", {"projects": {"Missing.csproj|net10.0": "."}}, "Unknown configured graph layout project"),
        ("layout_escape", {"projects": {"App.csproj|net10.0": "../outside"}}, "Graph layout destination must be a safe"),
    ]:
        msbuild_graph_layouts(name = case, graph = ":graph", tags = ["manual"], **attrs)
        failure_test(name + "_" + case, ":" + case, message)
    msbuild_graph_output(name = "file", graph = ":graph", path = "bin/Release/net10.0/App.dll", tags = ["manual"])
    for case, attrs, message in [
        ("worker_paths", {"linux_worker": True}, "Graph workers require linux_stable_paths"),
        ("cache", {"worker_cache_mb": -1}, "worker_cache_mb must be nonnegative"),
        ("source_root", {"source_root": "other"}, "Graph source is outside source_root"),
        ("input_escape", {"input_paths": {"payload.txt": "../outside"}}, "Graph input_paths requires safe"),
    ]:
        msbuild_graph(name = case, **dict(common, **attrs))
        failure_test(name + "_" + case, ":" + case, message)
    msbuild_graph_restore(name = "safe_restore", linux_stable_paths = True, **common)
    msbuild_graph_output(name = "restore_tree", graph = ":safe_restore", path = "obj", directory = True, tags = ["manual"])
    msbuild_graph_restore(name = "unsafe_restore", **common)
    failure_test(name + "_restore_paths", ":unsafe_restore", "Prepared Restore requires linux_stable_paths")
    msbuild_tool(name = "unsafe_tool", layout = ":tool_layout", entry_point = "../Tasks.dll", tags = ["manual"])
    failure_test(name + "_tool_escape", ":unsafe_tool", "Tool entry_point must be a safe")
    msbuild_graph_output(name = "unsafe_output", graph = ":graph", path = "../outside", tags = ["manual"])
    failure_test(name + "_output_escape", ":unsafe_output", "Graph output requires a safe")
    msbuild_graph_binary(name = "missing_project", graph = ":graph", project = "Missing.csproj", tags = ["manual"])
    failure_test(name + "_project", ":missing_project", "Select one generated project/framework")
    msbuild_graph(name = "multiple_frameworks", project_outputs = {
        "App.csproj|net9.0": ["bin/net9.0", "App.dll", "Exe"],
        "App.csproj|net10.0": ["bin/net10.0", "App.dll", "Exe"],
    }, **common)
    msbuild_graph_binary(name = "ambiguous_binary", graph = ":multiple_frameworks", project = "App.csproj", tags = ["manual"])
    failure_test(name + "_ambiguous_binary", ":ambiguous_binary", "Select one generated project/framework with project and framework: App.csproj")
    msbuild_graph_layout(name = "ambiguous_layout", graph = ":multiple_frameworks", project = "App.csproj", tags = ["manual"])
    failure_test(name + "_ambiguous_layout", ":ambiguous_layout", "Select one generated project/framework with project and framework: App.csproj")
    msbuild_graph_layout(name = "selected_layout", graph = ":multiple_frameworks", project = "App.csproj", framework = "net10.0", tags = ["manual"])
    analysis_test(name = name + "_selected_layout", target = ":selected_layout", impl = _selected_layout)
    msbuild_graph(name = "unsafe_project_output", project_outputs = {"App.csproj|net10.0": ["../bin", "App.dll", "Exe"]}, **common)
    msbuild_graph_binary(name = "unsafe_binary", graph = ":unsafe_project_output", project = "App.csproj", tags = ["manual"])
    failure_test(name + "_unsafe_binary", ":unsafe_binary", "Runtime outputs must be safe workspace-relative paths")
    msbuild_graph_layout(name = "unsafe_layout", graph = ":unsafe_project_output", project = "App.csproj", tags = ["manual"])
    failure_test(name + "_unsafe_layout", ":unsafe_layout", "Graph layout requires safe workspace-relative outputs")
    msbuild_graph_layouts(name = "unsafe_combined_layout", graph = ":unsafe_project_output", projects = {"App.csproj|net10.0": "."}, tags = ["manual"])
    failure_test(name + "_unsafe_combined_layout", ":unsafe_combined_layout", "Graph layout requires safe workspace-relative outputs")
    for case, attrs, message in [
        ("coverage_executable", {"test_coverage": "coverlet"}, "test_coverage requires the mtp or vstest test protocol"),
        ("coverage_collector_protocol", {"test_protocol": "mtp", "test_coverage": "coverlet", "test_coverage_collector": ":direct_test_tool"}, "test_coverage_collector requires VSTest Coverlet coverage"),
        ("coverage_collector_missing", {"test_protocol": "vstest", "test_coverage": "coverlet", "test_runner": ":direct_test_tool"}, "VSTest Coverlet coverage requires test_coverage_collector"),
        ("exit_range", {"expected_exit_code": 256}, "expected_exit_code must be between"),
        ("exit_protocol", {"expected_exit_code": 100, "test_protocol": "mtp"}, "expected_exit_code requires"),
        ("settings", {"test_settings": "settings.xml", "test_settings_output": "generated.xml"}, "Declare either test_settings or test_settings_output"),
        ("test_directory", {"test_working_directory": "../outside"}, "test_working_directory must be a safe"),
        ("runner", {"test_protocol": "vstest"}, "VSTest requires an explicit test_runner"),
        ("sharding", {"shard_count": 2}, "Executable tests do not yet support sharding"),
    ]:
        msbuild_graph_test(name = case, graph = ":graph", project = "App.csproj", tags = ["manual"], **attrs)
        failure_test(name + "_" + case, ":" + case, message)
