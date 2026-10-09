"""Verified SDK acquisition and downloaded/source-built runtime integration."""

load("//msbuild/private:global_json.bzl", "global_json_sdk")
load("//msbuild/private:sdk_metadata.bzl", "resolve_runtime", "resolve_sdk", "runtime_selection", "sdk_download", "sdk_platforms", "sdk_policy_version", "sdk_selection", "sdk_version", "select_sdk_version")
load("//msbuild/private:sdk_repositories.bzl", "sdk_archive", "sdk_toolchains")

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
    if ctx.attr.kind == "aspnetcore":
        for path in ["shared/Microsoft.NETCore.App", "shared/Microsoft.AspNetCore.App/" + ctx.attr.version]:
            if not ctx.path("runtime/" + path).exists:
                fail("ASP.NET runtime archive is missing declared layout component: " + path)
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
        "kind": attr.string(default = "coreclr", values = ["coreclr", "aspnetcore"]),
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

def _metadata_urls(declaration, version):
    return declaration.metadata_urls or ["https://builds.dotnet.microsoft.com/dotnet/release-metadata/%s/releases.json" % ".".join(version.split(".")[:2])]

def _sdk_pin(ctx, declaration, policies, facts):
    if not declaration.global_json:
        return (declaration.version, None)
    request = global_json_sdk(ctx.read(declaration.global_json))
    sdk_version(request["version"])
    if request["rollForward"] == "disable":
        return (sdk_policy_version(request["version"], request), None)
    urls = _metadata_urls(declaration, request["version"])
    key = json.encode([request["version"], request["rollForward"], request["allowPrerelease"], urls])
    if key in policies:
        return (sdk_policy_version(policies[key], request), None)

    # Existing exact selections remain usable after upgrading the extension.
    if request["rollForward"] == "patch" and json.encode([request["version"], urls]) in facts:
        policies[key] = sdk_policy_version(request["version"], request)
        return (request["version"], None)
    path = "sdk-policy-%s.json" % len(policies)
    ctx.download(urls, output = path)
    metadata = ctx.read(path)
    version = select_sdk_version(metadata, request)
    policies[key] = version
    return (version, metadata)

def _selection(ctx, declaration, version, facts, kind, metadata = None):
    urls = _metadata_urls(declaration, version)
    key = json.encode([version, urls])

    # Preserve existing CoreCLR/SDK facts; ASP.NET distributions have separate keys.
    if kind == "aspnetcore":
        key = json.encode([version, urls, kind])
    validate = sdk_selection if kind == "sdk" else runtime_selection
    selected = validate(facts[key]) if key in facts else None
    missing = [platform for platform in declaration.platforms if selected == None or platform not in selected["platforms"]]
    if missing:
        path = "%s-metadata-%s.json" % (kind, len(facts))
        if metadata == None:
            ctx.download(urls, output = path)
            metadata = ctx.read(path)
        resolved = resolve_sdk(metadata, version, missing) if kind == "sdk" else resolve_runtime(metadata, version, missing, kind)
        if selected != None:
            if kind == "sdk" and selected["runtime"] != resolved["runtime"]:
                fail("SDK release metadata conflicts with recorded runtime: " + version)
            resolved["platforms"].update(selected["platforms"])
        selected = resolved
        facts[key] = selected
    return selected

def _runtimes(ctx):
    names = {}
    facts = dict(ctx.facts.get("sdk-v1", {}))
    runtime_facts = dict(ctx.facts.get("runtime-v1", {}))
    policies = dict(ctx.facts.get("sdk-policy-v1", {}))
    for mod in ctx.modules:
        for sdk in mod.tags.sdk:
            if sdk.name in names:
                fail("Duplicate SDK/runtime repository name: " + sdk.name)
            names[sdk.name] = True
            if bool(sdk.version) == bool(sdk.global_json):
                fail("Specify exactly one of sdk.version or sdk.global_json")
            version, metadata = _sdk_pin(ctx, sdk, policies, facts)
            sdk_version(version)
            sdk_platforms(sdk.platforms)
            locked = _selection(ctx, sdk, version, facts, "sdk", metadata)
            repositories = {}
            for platform in sdk.platforms:
                name = sdk.name + "_" + platform.replace("-", "_")
                repositories[platform] = name
                sdk_archive(name = name, version = version, runtime_version = locked["runtime"], platform = platform, **locked["platforms"][platform])
            sdk_toolchains(name = sdk.name, repositories = repositories)
        for archive in mod.tags.sdk_archive:
            if archive.name in names:
                fail("Duplicate SDK/runtime repository name: " + archive.name)
            names[archive.name] = True
            sdk_platforms([archive.platform])
            sdk_version(archive.version)
            sdk_version(archive.runtime_version)
            sdk_download({"urls": archive.urls, "integrity": archive.integrity})
            name = archive.name + "_" + archive.platform.replace("-", "_")
            sdk_archive(name = name, version = archive.version, runtime_version = archive.runtime_version, platform = archive.platform, urls = archive.urls, integrity = archive.integrity)
            sdk_toolchains(name = archive.name, repositories = {archive.platform: name})
        for runtime in mod.tags.runtime:
            if runtime.name in names:
                fail("Duplicate runtime repository name: " + runtime.name)
            names[runtime.name] = True
            sdk_version(runtime.version)
            if not runtime.platforms or len(runtime.platforms) != len({p: True for p in runtime.platforms}):
                fail("Runtime platforms must be nonempty and unique")
            for platform in runtime.platforms:
                if platform not in _PLATFORMS:
                    fail("Unsupported runtime platform: " + platform)
            kind = "aspnetcore" if runtime.kind == "aspnetcore" else "runtime"
            locked = _selection(ctx, runtime, runtime.version, runtime_facts, kind)
            repositories = {}
            for platform in runtime.platforms:
                name = runtime.name + "_" + platform.replace("-", "_")
                repositories[platform] = name
                _runtime_archive(name = name, version = runtime.version, platform = platform, kind = runtime.kind, **locked["platforms"][platform])
            _runtime_aliases(name = runtime.name, repositories = repositories)
        for archive in mod.tags.runtime_archive:
            if archive.name in names:
                fail("Duplicate runtime repository name: " + archive.name)
            names[archive.name] = True
            if archive.platform not in _PLATFORMS:
                fail("Unsupported runtime platform: " + archive.platform)
            _runtime_archive(name = archive.name, version = archive.version, platform = archive.platform, urls = archive.urls, integrity = archive.integrity)

    return ctx.extension_metadata(facts = {"sdk-v1": facts, "runtime-v1": runtime_facts, "sdk-policy-v1": policies})

_dotnet_runtime = tag_class(attrs = {
    "name": attr.string(mandatory = True),
    "version": attr.string(mandatory = True),
    "kind": attr.string(default = "coreclr", values = ["coreclr", "aspnetcore"]),
    "metadata_urls": attr.string_list(),
    "platforms": attr.string_list(default = ["linux-arm64", "linux-x64", "osx-arm64", "osx-x64"]),
})

_custom_runtime = tag_class(attrs = {
    "name": attr.string(mandatory = True),
    "version": attr.string(mandatory = True),
    "platform": attr.string(mandatory = True),
    "urls": attr.string_list(mandatory = True),
    "integrity": attr.string(mandatory = True),
})

_dotnet_sdk = tag_class(attrs = {
    "name": attr.string(mandatory = True),
    "version": attr.string(),
    "global_json": attr.label(),
    "metadata_urls": attr.string_list(),
    "platforms": attr.string_list(default = ["linux-arm64", "linux-x64", "osx-arm64", "osx-x64"]),
})

_custom_sdk = tag_class(attrs = {
    "name": attr.string(mandatory = True),
    "version": attr.string(mandatory = True),
    "runtime_version": attr.string(mandatory = True),
    "platform": attr.string(mandatory = True),
    "urls": attr.string_list(mandatory = True),
    "integrity": attr.string(mandatory = True),
})

dotnet = module_extension(
    implementation = _runtimes,
    tag_classes = {"sdk": _dotnet_sdk, "sdk_archive": _custom_sdk, "runtime": _dotnet_runtime, "runtime_archive": _custom_runtime},
)
