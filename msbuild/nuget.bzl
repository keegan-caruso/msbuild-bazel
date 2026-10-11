"""Acquire the closed archive inventory emitted by the explicit NuGet update job."""

def _archive(ctx):
    ctx.download(ctx.attr.urls, output = ctx.attr.filename, sha256 = ctx.attr.sha256, canonical_id = ctx.attr.sha256)
    ctx.file("BUILD.bazel", 'exports_files([%s], visibility=["//visibility:public"])\n' % json.encode(ctx.attr.filename))

_archive_repo = repository_rule(implementation = _archive, attrs = {
    "urls": attr.string_list(mandatory = True),
    "sha256": attr.string(mandatory = True),
    "filename": attr.string(mandatory = True),
})

def _inventory(ctx):
    rows = ['load(%s, "msbuild_nuget_package", "msbuild_package_lock")' % json.encode(str(ctx.attr._defs)), 'package(default_visibility=["//visibility:public"])']
    packages = json.decode(ctx.attr.packages)
    for p in packages:
        rows.append("msbuild_nuget_package(name=%s, package_id=%s, version=%s, archive=%s, archive_sha256=%s, content_hash=%s)" % tuple([json.encode(p[key]) for key in ["name", "id", "version", "archive", "sha256", "archiveSha512"]]))
    rows.append('msbuild_package_lock(name="packages", packages=%s, allow_multiple_versions=True)' % json.encode([":" + p["name"] for p in packages]))
    rows.append('filegroup(name="archives", srcs=%s)' % json.encode([p["archive"] for p in packages]))
    ctx.file("BUILD.bazel", "\n".join(rows) + "\n")

_inventory_repo = repository_rule(implementation = _inventory, attrs = {
    "packages": attr.string(mandatory = True),
    "_defs": attr.label(default = Label("//msbuild:defs.bzl")),
})

def _safe(value):
    return type(value) == "string" and bool(value) and all([c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in value.elems()]) and value not in [".", ".."]

def _nuget(ctx):
    names = {}
    for mod in ctx.modules:
        for tag in mod.tags.lock:
            if tag.name in names:
                fail("Duplicate NuGet inventory: " + tag.name)
            names[tag.name] = True
            data = json.decode(ctx.read(tag.lockfile))
            if data.get("version") != 1 or data.get("generatedBy") != "RulesMSBuild.NuGetUpdate" or type(data.get("packages")) != "list":
                fail("Expected a generated version-1 NuGet archive manifest")
            packages = []
            identities = {}
            targets = {}
            filenames = {}
            for p in data["packages"]:
                if type(p) != "dict" or sorted(p.keys()) != sorted(["id", "version", "sha256", "archiveSha512", "urls"]):
                    fail("Invalid NuGet archive fields")
                if not _safe(p["id"]) or not _safe(p["version"]):
                    fail("Unsafe NuGet identity")
                identity = p["id"].lower() + "/" + p["version"].lower()
                target = p["id"].lower() + "__" + p["version"].lower()
                if identity in identities or target in targets:
                    fail("Duplicate or colliding NuGet identity: " + identity)
                identities[identity] = True
                targets[target] = True
                if type(p["sha256"]) != "string" or len(p["sha256"]) != 64 or any([c not in "0123456789abcdef" for c in p["sha256"].elems()]):
                    fail("NuGet archive requires a lowercase SHA256")
                if type(p["archiveSha512"]) != "string" or len(p["archiveSha512"]) != 88 or not p["archiveSha512"].endswith("=="):
                    fail("NuGet archive requires a raw archive SHA512")
                if type(p["urls"]) != "list" or not p["urls"] or any([type(url) != "string" or not (url.startswith("https://") or url.startswith("http://")) or "@" in url or "?" in url or "#" in url for url in p["urls"]]):
                    fail("NuGet archives require HTTP(S) URLs without embedded credentials")
                filename = p["id"].lower() + "." + p["version"].lower() + ".nupkg"
                if filename in filenames:
                    fail("Colliding NuGet archive filename: " + filename)
                filenames[filename] = True
                repo = tag.name + "_" + target
                _archive_repo(name = repo, urls = p["urls"], sha256 = p["sha256"], filename = filename)
                packages.append(dict(p, name = target, archive = "@" + repo + "//:" + filename))
            _inventory_repo(name = tag.name, packages = json.encode(packages))
    return ctx.extension_metadata(reproducible = True)

_lock = tag_class(attrs = {"name": attr.string(mandatory = True), "lockfile": attr.label(mandatory = True)})

nuget = module_extension(implementation = _nuget, tag_classes = {"lock": _lock})
