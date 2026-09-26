"""Download SDKs and generate bootstrap and platform toolchain targets."""

SDK_PLATFORMS = {
    "linux-arm64": ["@platforms//os:linux", "@platforms//cpu:aarch64"],
    "linux-x64": ["@platforms//os:linux", "@platforms//cpu:x86_64"],
    "osx-arm64": ["@platforms//os:osx", "@platforms//cpu:aarch64"],
    "osx-x64": ["@platforms//os:osx", "@platforms//cpu:x86_64"],
}

def _sdk_archive(ctx):
    ctx.download_and_extract(url = ctx.attr.urls, integrity = ctx.attr.integrity, output = "sdk", canonical_id = ctx.attr.integrity)
    ctx.file("runtime-roots.json", "[]")
    ctx.file("BUILD.bazel", """load(%s, "sdk_runner", "sdk_runtime", "sdk_runtime_toolchain")
load(%s, "msbuild_toolchain")
package(default_visibility = ["//visibility:public"])
filegroup(name = "files", srcs = glob(["sdk/**"], exclude = ["sdk/**/BUILD", "sdk/**/BUILD.bazel"]))
sdk_runner(name = "runner_payload", dotnet = "sdk/dotnet", sdk = ":files", project = %s, sources = %s)
filegroup(name = "runner", srcs = [":runner_payload"], output_group = "runner")
msbuild_toolchain(name = "sdk_toolchain", dotnet = "sdk/dotnet", sdk = ":files", runner = ":runner", runner_support = [":runner_payload"], runtime_manifest = "runtime-roots.json", sdk_version = %s, requires_runtime_toolchain = True)
filegroup(name = "runtime_files", srcs = ["sdk/dotnet"] + glob(["sdk/host/**", "sdk/shared/**"]))
sdk_runtime(name = "runtime", dotnet = "sdk/dotnet", files = ":runtime_files", runtime_identifier = %s, version = %s)
sdk_runtime(name = "sdk_host", dotnet = "sdk/dotnet", files = ":files", runtime_identifier = %s, version = %s)
sdk_runtime_toolchain(name = "runtime_toolchain", runtime = ":runtime")
""" % (json.encode(str(ctx.attr._bootstrap)), json.encode(str(ctx.attr._toolchain)), json.encode(str(ctx.attr._project)), json.encode(str(ctx.attr._sources)), json.encode(ctx.attr.version), json.encode(ctx.attr.platform), json.encode(ctx.attr.runtime_version), json.encode(ctx.attr.platform), json.encode(ctx.attr.runtime_version)))

sdk_archive = repository_rule(
    implementation = _sdk_archive,
    attrs = {
        "urls": attr.string_list(mandatory = True),
        "integrity": attr.string(mandatory = True),
        "version": attr.string(mandatory = True),
        "runtime_version": attr.string(mandatory = True),
        "platform": attr.string(mandatory = True),
        "_bootstrap": attr.label(default = Label("//msbuild/private:sdk_bootstrap.bzl")),
        "_toolchain": attr.label(default = Label("//msbuild:toolchain.bzl")),
        "_project": attr.label(default = Label("//tools/ExplicitBuild:ExplicitBuild.csproj")),
        "_sources": attr.label(default = Label("//tools/ExplicitBuild:sources")),
    },
)

def _sdk_toolchains(ctx):
    rows = ['package(default_visibility = ["//visibility:public"])']
    choices = {}
    sdk_hosts = {}
    for platform, repo in ctx.attr.repositories.items():
        constraints = json.encode(SDK_PLATFORMS[platform])
        name = platform.replace("-", "_")
        rows.append("toolchain(name=%s, toolchain=%s, toolchain_type=%s, exec_compatible_with=%s)" % (json.encode("sdk_" + name), json.encode("@" + repo + "//:sdk_toolchain"), json.encode(str(ctx.attr._sdk_type)), constraints))
        rows.append("toolchain(name=%s, toolchain=%s, toolchain_type=%s, target_compatible_with=%s)" % (json.encode("runtime_" + name), json.encode("@" + repo + "//:runtime_toolchain"), json.encode(str(ctx.attr._runtime_type)), constraints))
        rows.append("config_setting(name=%s, constraint_values=%s)" % (json.encode(name), constraints))
        choices[":" + name] = "@" + repo + "//:runtime"
        sdk_hosts[":" + name] = "@" + repo + "//:sdk_host"
    rows.append("alias(name=\"runtime\", actual=select(%s, no_match_error=\"No SDK runtime for the target platform\"))" % json.encode(choices))
    rows.append("alias(name=\"sdk_host\", actual=select(%s, no_match_error=\"No SDK host for the target platform\"))" % json.encode(sdk_hosts))
    ctx.file("BUILD.bazel", "\n".join(rows) + "\n")

sdk_toolchains = repository_rule(
    implementation = _sdk_toolchains,
    attrs = {
        "repositories": attr.string_dict(),
        "_sdk_type": attr.label(default = Label("//msbuild:toolchain_type")),
        "_runtime_type": attr.label(default = Label("//msbuild:runtime_toolchain_type")),
    },
)
