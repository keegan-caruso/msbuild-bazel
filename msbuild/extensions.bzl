"""Verified runtime downloads sharing the source-built runtime provider."""

load("//msbuild/private:runtime_downloads.bzl", "RUNTIME_DOWNLOADS")

_PLATFORMS = {
    "linux-arm64": ["@platforms//os:linux", "@platforms//cpu:aarch64"],
    "linux-x64": ["@platforms//os:linux", "@platforms//cpu:x86_64"],
    "osx-arm64": ["@platforms//os:osx", "@platforms//cpu:aarch64"],
    "osx-x64": ["@platforms//os:osx", "@platforms//cpu:x86_64"],
}

def _archive(ctx):
    if not ctx.attr.integrity:
        fail("Runtime archives require integrity")
    ctx.download_and_extract(
        url = ctx.attr.urls,
        integrity = ctx.attr.integrity,
        output = "runtime",
        canonical_id = ctx.attr.integrity,
    )
    if not ctx.path("runtime/dotnet").exists:
        fail("Runtime archive must contain dotnet at its root")
    ctx.file("BUILD.bazel", """load(%s, "msbuild_layout", "msbuild_runtime")
package(default_visibility = ["//visibility:public"])
msbuild_layout(
    name = "layout",
    paths = {p: p[len("runtime/"):] for p in glob(["runtime/**"], allow_empty = False)},
)
msbuild_runtime(
    name = "runtime",
    layout = ":layout",
    entry_point = "dotnet",
    runtime_identifier = %s,
    version = %s,
    target_compatible_with = %s,
)
""" % (json.encode(str(ctx.attr._defs)), json.encode(ctx.attr.platform), json.encode(ctx.attr.version), json.encode(_PLATFORMS[ctx.attr.platform])))

_runtime_archive = repository_rule(
    implementation = _archive,
    attrs = {
        "urls": attr.string_list(mandatory = True),
        "integrity": attr.string(mandatory = True),
        "version": attr.string(mandatory = True),
        "platform": attr.string(mandatory = True),
        "_defs": attr.label(default = Label("//msbuild:defs.bzl")),
    },
)

def _aliases(ctx):
    declarations = ['package(default_visibility = ["//visibility:public"])']
    choices = {}
    for platform, repository in ctx.attr.repositories.items():
        declarations.append("config_setting(name = %s, constraint_values = %s)" % (json.encode(platform), json.encode(_PLATFORMS[platform])))
        choices[":" + platform] = "@" + repository + "//:runtime"
    declarations.append("alias(name = \"runtime\", actual = select(%s, no_match_error = \"No downloaded runtime for the selected target platform\"))" % json.encode(choices))
    ctx.file("BUILD.bazel", "\n".join(declarations) + "\n")

_runtime_aliases = repository_rule(implementation = _aliases, attrs = {"repositories": attr.string_dict()})

def _runtimes(ctx):
    names = {}
    for mod in ctx.modules:
        for runtime in mod.tags.runtime:
            if runtime.name in names:
                fail("Duplicate runtime repository name: " + runtime.name)
            names[runtime.name] = True
            if runtime.version not in RUNTIME_DOWNLOADS:
                fail("Unknown runtime version %s; use runtime_archive with explicit URLs and integrity" % runtime.version)
            if not runtime.platforms or len(runtime.platforms) != len({p: True for p in runtime.platforms}):
                fail("Runtime platforms must be nonempty and unique")
            repositories = {}
            for platform in runtime.platforms:
                if platform not in _PLATFORMS:
                    fail("Unsupported runtime platform: " + platform)
                name = runtime.name + "_" + platform.replace("-", "_")
                repositories[platform] = name
                _runtime_archive(name = name, version = runtime.version, platform = platform, **RUNTIME_DOWNLOADS[runtime.version][platform])
            _runtime_aliases(name = runtime.name, repositories = repositories)
        for archive in mod.tags.runtime_archive:
            if archive.name in names:
                fail("Duplicate runtime repository name: " + archive.name)
            names[archive.name] = True
            if archive.platform not in _PLATFORMS:
                fail("Unsupported runtime platform: " + archive.platform)
            _runtime_archive(name = archive.name, version = archive.version, platform = archive.platform, urls = archive.urls, integrity = archive.integrity)

_dotnet_runtime = tag_class(attrs = {
    "name": attr.string(mandatory = True),
    "version": attr.string(mandatory = True),
    "platforms": attr.string_list(default = ["linux-arm64", "linux-x64", "osx-arm64", "osx-x64"]),
})

_custom_runtime = tag_class(attrs = {
    "name": attr.string(mandatory = True),
    "version": attr.string(mandatory = True),
    "platform": attr.string(mandatory = True),
    "urls": attr.string_list(mandatory = True),
    "integrity": attr.string(mandatory = True),
})

dotnet = module_extension(
    implementation = _runtimes,
    tag_classes = {"runtime": _dotnet_runtime, "runtime_archive": _custom_runtime},
)
