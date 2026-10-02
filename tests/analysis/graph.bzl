"""Graph inputs, worker defaults, complete layouts and launch contracts."""

load("@rules_testing//lib:analysis_test.bzl", "analysis_test")
load("//msbuild:defs.bzl", "MSBuildLayoutInfo", "MSBuildRuntimeInfo", "MSBuildToolInfo", "msbuild_file_binding", "msbuild_graph", "msbuild_graph_binary", "msbuild_graph_layout", "msbuild_graph_output", "msbuild_graph_restore", "msbuild_graph_test", "msbuild_layout", "msbuild_runtime", "msbuild_tool")
load(":helpers.bzl", "action", "failure_test", "paths", "request")

def _inputs(env, targets):
    build = action(targets.graph, "MSBuildGraph")
    env.expect.that_collection(paths(build.inputs)).contains_at_least(["tests/analysis/App.csproj", "tests/analysis/Source.cs", "tests/analysis/contract.json", "tests/analysis/sdk.txt"])
    env.expect.that_collection(build.argv).contains("0")
    env.expect.that_str(targets.tool[MSBuildToolInfo].entry_point).equals("Tasks.dll")
    env.expect.that_str(targets.tool[MSBuildToolInfo].directory.short_path).equals(targets.layout[MSBuildLayoutInfo].directory.short_path)

def _worker(env, target):
    env.expect.that_bool(request(target, ".graph-request.json")["profileBuild"]).equals(False)

def _launch(env, targets):
    host = targets.host[MSBuildRuntimeInfo]
    env.expect.that_str(request(targets.app, ".launch.json")["runtimeHost"]["launchMode"]).equals("corerun")
    env.expect.that_collection(targets.app[DefaultInfo].default_runfiles.files.to_list()).contains_at_least(host.files.to_list())
    env.expect.that_collection(paths(targets.app[DefaultInfo].default_runfiles.files)).not_contains("tests/analysis/sdk.txt")

def graph_tests(name):
    """Declare graph analysis controls.

    Args:
        name: Test prefix.
    """
    common = {"runner": ":runner_payload", "contract": "contract.json", "srcs": ["App.csproj", "Source.cs"], "tags": ["manual"]}
    msbuild_layout(name = "tool_layout", paths = {"Runner.dll": "Tasks.dll"}, tags = ["manual"])
    msbuild_tool(name = "task_tool", layout = ":tool_layout", entry_point = "Tasks.dll", tags = ["manual"])
    msbuild_file_binding(name = "binding", tool = ":task_tool", property_name = "TaskLocation", tags = ["manual"])
    msbuild_graph(name = "graph", bindings = [":binding"], project_outputs = {"App.csproj|net10.0": ["bin/Release/net10.0", "App.dll", "Exe"]}, **common)
    msbuild_graph(name = "worker", linux_worker = True, linux_stable_paths = True, **common)
    analysis_test(name = name + "_inputs", targets = {"graph": ":graph", "tool": ":task_tool", "layout": ":tool_layout"}, impl = _inputs)
    analysis_test(name = name + "_worker", target = ":worker", impl = _worker)
    msbuild_runtime(name = "source_host", layout = ":tool_layout", entry_point = "corerun", launch_mode = "corerun", tags = ["manual"])
    msbuild_graph_binary(name = "app", graph = ":graph", project = "App.csproj", runtime_host = ":source_host", tags = ["manual"])
    analysis_test(name = name + "_launch", targets = {"host": ":source_host", "app": ":app"}, impl = _launch)
    msbuild_graph_layout(name = "export", graph = ":graph", project = "App.csproj", tags = ["manual"])
    msbuild_graph_output(name = "file", graph = ":graph", path = "bin/Release/net10.0/App.dll", tags = ["manual"])
    for case, attrs, message in [
        ("worker_paths", {"linux_worker": True}, "Graph workers require linux_stable_paths"),
        ("cache", {"worker_cache_mb": -1}, "worker_cache_mb must be nonnegative"),
        ("source_root", {"source_root": "other"}, "Graph source is outside source_root"),
        ("input_escape", {"input_paths": {"payload.txt": "../outside"}}, "Graph input_paths requires safe"),
    ]:
        msbuild_graph(name = case, **dict(common, **attrs))
        failure_test(name + "_" + case, ":" + case, message)
    msbuild_graph_restore(name = "unsafe_restore", **common)
    failure_test(name + "_restore_paths", ":unsafe_restore", "Prepared Restore requires linux_stable_paths")
    msbuild_tool(name = "unsafe_tool", layout = ":tool_layout", entry_point = "../Tasks.dll", tags = ["manual"])
    failure_test(name + "_tool_escape", ":unsafe_tool", "Tool entry_point must be a safe")
    msbuild_graph_output(name = "unsafe_output", graph = ":graph", path = "../outside", tags = ["manual"])
    failure_test(name + "_output_escape", ":unsafe_output", "Graph output requires a safe")
    msbuild_graph_binary(name = "missing_project", graph = ":graph", project = "Missing.csproj", tags = ["manual"])
    failure_test(name + "_project", ":missing_project", "Select one generated project/framework")
    for case, attrs, message in [
        ("settings", {"test_settings": "settings.xml", "test_settings_output": "generated.xml"}, "Declare either test_settings or test_settings_output"),
        ("test_directory", {"test_working_directory": "../outside"}, "test_working_directory must be a safe"),
        ("runner", {"test_protocol": "vstest"}, "VSTest requires an explicit test_runner"),
        ("sharding", {"shard_count": 2}, "Executable tests do not yet support sharding"),
    ]:
        msbuild_graph_test(name = case, graph = ":graph", project = "App.csproj", tags = ["manual"], **attrs)
        failure_test(name + "_" + case, ":" + case, message)
