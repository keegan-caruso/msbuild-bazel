"""Download SDKs and generate bootstrap and platform toolchain targets."""

load(":paths.bzl", "quote")

SDK_PLATFORMS = {
    "linux-arm64": ["@platforms//os:linux", "@platforms//cpu:aarch64"],
    "linux-x64": ["@platforms//os:linux", "@platforms//cpu:x86_64"],
    "osx-arm64": ["@platforms//os:osx", "@platforms//cpu:aarch64"],
    "osx-x64": ["@platforms//os:osx", "@platforms//cpu:x86_64"],
}

def _sdk_archive(ctx):
    if not ctx.attr.integrity:
        fail("SDK archives require integrity")
    ctx.download_and_extract(url = ctx.attr.urls, integrity = ctx.attr.integrity, output = "sdk", canonical_id = ctx.attr.integrity)
    for path in ["dotnet", "sdk/" + ctx.attr.version, "shared/Microsoft.NETCore.App/" + ctx.attr.runtime_version]:
        if not ctx.path("sdk/" + path).exists:
            fail("SDK archive is missing declared layout component: " + path)
    ctx.file("BUILD.bazel", """load(%s, "msbuild_sdk")
package(default_visibility = ["//visibility:public"])
filegroup(name = "files", srcs = glob(["sdk/**"], exclude = ["sdk/**/BUILD", "sdk/**/BUILD.bazel"]))
msbuild_sdk(name = "sdk", dotnet = "sdk/dotnet", files = [":files"], sdk_version = %s, runtime_identifier = %s, runtime_version = %s)
""" % (json.encode(str(ctx.attr._declarations)), json.encode(ctx.attr.version), json.encode(ctx.attr.platform), json.encode(ctx.attr.runtime_version)))

sdk_archive = repository_rule(
    implementation = _sdk_archive,
    attrs = {
        "urls": attr.string_list(mandatory = True),
        "integrity": attr.string(mandatory = True),
        "version": attr.string(mandatory = True),
        "runtime_version": attr.string(mandatory = True),
        "_declarations": attr.label(default = Label("//msbuild:sdk.bzl")),
        "platform": attr.string(mandatory = True),
    },
)

def _sdk_toolchains(ctx):
    rows = ['package(default_visibility = ["//visibility:public"])']
    if ctx.attr.update_name:
        rows.insert(0, "load(%s, \"sdk_update\")" % json.encode(str(ctx.attr._updater)))
        ctx.template("update.sh", ctx.attr._update, {"@@SDK_NAME@@": quote(ctx.attr.update_name)}, executable = True)
        rows.append('sdk_update(name="update", script="update.sh")')
    choices = {}
    sdk_hosts = {}
    sdk_files = {}
    executables = {}
    for platform, repo in ctx.attr.repositories.items():
        constraints = json.encode(SDK_PLATFORMS[platform])
        name = platform.replace("-", "_")
        rows.append("toolchain(name=%s, toolchain=%s, toolchain_type=%s, exec_compatible_with=%s)" % (json.encode("sdk_" + name), json.encode("@" + repo + "//:sdk_toolchain"), json.encode(str(ctx.attr._sdk_type)), constraints))
        rows.append("toolchain(name=%s, toolchain=%s, toolchain_type=%s, target_compatible_with=%s)" % (json.encode("runtime_" + name), json.encode("@" + repo + "//:sdk_runtime_toolchain"), json.encode(str(ctx.attr._runtime_type)), constraints))
        rows.append("config_setting(name=%s, constraint_values=%s)" % (json.encode(name), constraints))
        choices[":" + name] = "@" + repo + "//:sdk_runtime"
        sdk_hosts[":" + name] = "@" + repo + "//:sdk_host"
        sdk_files[":" + name] = "@" + repo + "//:files"
        executables[":" + name] = "@" + repo + "//:sdk/dotnet"
    rows.append("alias(name=\"runtime\", actual=select(%s, no_match_error=\"No SDK runtime for the target platform\"))" % json.encode(choices))
    rows.append("alias(name=\"sdk_host\", actual=select(%s, no_match_error=\"No SDK host for the target platform\"))" % json.encode(sdk_hosts))
    rows.append("alias(name=\"files\", actual=select(%s))" % json.encode(sdk_files))
    rows.append("alias(name=\"dotnet\", actual=select(%s))" % json.encode(executables))
    ctx.file("BUILD.bazel", "\n".join(rows) + "\n")

sdk_toolchains = repository_rule(
    implementation = _sdk_toolchains,
    attrs = {
        "repositories": attr.string_dict(),
        "update_name": attr.string(),
        "_update": attr.label(default = Label("//msbuild/private:sdk-update.sh")),
        "_updater": attr.label(default = Label("//msbuild/private:sdk_update.bzl")),
        "_sdk_type": attr.label(default = Label("//msbuild:toolchain_type")),
        "_runtime_type": attr.label(default = Label("//msbuild:runtime_toolchain_type")),
    },
)
