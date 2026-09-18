"""Native VSTest execution consuming sealed graph outputs and declared test data."""

load(":native_cache.bzl", "NativeBundle")

def _runfile(ctx, file):
    path = file.short_path
    return path[3:] if path.startswith("../") else ctx.workspace_name + "/" + path

def _native_test_impl(ctx):
    names = ctx.attr.expected_tests
    if not names or len({name: True for name in names}) != len(names) or any([not name for name in names]):
        fail("expected_tests must contain unique nonempty test names")
    request = ctx.actions.declare_file(ctx.label.name + ".request.json")
    launcher = ctx.actions.declare_file(ctx.label.name + ".sh")
    bundle = ctx.attr.subject[NativeBundle].bundle
    bundles = depset([bundle])
    data = []
    for file in ctx.files.data:
        destination = file.short_path.removeprefix("test-data/")
        if destination not in ctx.attr.data_hashes:
            fail("missing declared test data hash: " + destination)
        data.append({"source": _runfile(ctx, file), "destination": destination, "sha256": ctx.attr.data_hashes[destination]})
    ctx.actions.write(request, json.encode({
        "schemaVersion": 1,
        "project": ctx.attr.project,
        "globalProperties": ctx.attr.global_properties,
        "bundles": [],
        "nativeBundle": _runfile(ctx, bundle),
        "nativeInputs": ctx.attr.native_inputs,
        "nativeToolchain": ctx.attr.native_toolchain,
        "runtimeDirectory": ctx.attr.runtime_directory,
        "assembly": ctx.attr.assembly,
        "testData": data,
        "expectedTests": ctx.attr.expected_tests,
        "sdkRoot": _runfile(ctx, ctx.executable.dotnet).rsplit("/", 1)[0],
        "sourceRoot": "/_/workspace",
    }))
    ctx.actions.write(launcher, "#!/bin/sh\nset -eu\nexec \"$TEST_SRCDIR/" + _runfile(ctx, ctx.executable.dotnet) + "\" \"$TEST_SRCDIR/" + _runfile(ctx, ctx.file.runner) + "\" --request \"$TEST_SRCDIR/" + _runfile(ctx, request) + "\"\n", is_executable = True)
    files = depset(ctx.files.data + ctx.files.runner_support + [ctx.file.runner, ctx.file.host_identity, request, ctx.executable.dotnet], transitive = [bundles, ctx.attr.sdk[DefaultInfo].files])
    return [
        DefaultInfo(executable = launcher, runfiles = ctx.runfiles(transitive_files = files)),
        testing.ExecutionInfo(requirements = {"no-remote": "1"}),
    ]

native_test = rule(implementation = _native_test_impl, test = True, attrs = {
    "subject": attr.label(providers = [NativeBundle], mandatory = True),
    "project": attr.string(mandatory = True),
    "native_inputs": attr.string(mandatory = True),
    "native_toolchain": attr.string(mandatory = True),
    "global_properties": attr.string_dict(mandatory = True),
    "runtime_directory": attr.string(mandatory = True),
    "assembly": attr.string(mandatory = True),
    "data": attr.label_list(allow_files = True),
    "data_hashes": attr.string_dict(),
    "expected_tests": attr.string_list(mandatory = True),
    "runner": attr.label(allow_single_file = True, mandatory = True),
    "runner_support": attr.label_list(allow_files = True),
    "host_identity": attr.label(allow_single_file = True, mandatory = True),
    "sdk": attr.label(mandatory = True),
    "dotnet": attr.label(allow_single_file = True, executable = True, cfg = "exec", mandatory = True),
})
