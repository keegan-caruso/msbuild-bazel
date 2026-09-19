"""Local tool wrapping and integrity-checked NuGet archive acquisition."""

def _tools(ctx):
    for name in ["Preparation", "GraphExport", "EvaluationProbe", "ReplayPlugin", "ActionRunner", "NativeProjectCache", "TestRunner"]:
        path = "tools/" + name + "/bin/Release/net10.0"
        ctx.symlink(ctx.attr.root + "/" + path, path)
    for path in ["tools/GraphExport/Bazel.GraphExport.targets", "tools/pilot-package-policy.json", "tools/discovery-test-packages.json", "tools/discovery-sdk-imports.json", "tools/orchard-discovery-policy.json", "tools/ActionRunner/Build/Action.props", "tools/ActionRunner/Build/Action.targets", "bazel/msbuild.bzl", "bazel/graph.bzl"]:
        ctx.symlink(ctx.attr.root + "/" + path, path)
    ctx.file("BUILD.bazel", 'filegroup(name="files", srcs=glob(["tools/**", "bazel/**"]), visibility=["//visibility:public"])\nexports_files(glob(["tools/**/*.dll", "tools/*.json"]))\n')

owned_tools = repository_rule(implementation = _tools, attrs = {"root": attr.string(mandatory = True)}, local = True)

def _base64(hexadecimal):
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    result = ""
    for offset in range(0, len(hexadecimal), 6):
        chunk = hexadecimal[offset:offset + 6]
        number = int(chunk + "0" * (6 - len(chunk)), 16)
        result += alphabet[number // 262144] + alphabet[(number // 4096) % 64]
        result += alphabet[(number // 64) % 64] if len(chunk) > 2 else "="
        result += alphabet[number % 64] if len(chunk) > 4 else "="
    return result

def _nuget(ctx):
    pins = json.decode(ctx.read(ctx.attr.policy))
    for package, digest in sorted(json.decode(ctx.attr.packages).items()):
        parts = package.split("/")
        if len(parts) != 2 or ".." in parts or package != package.lower():
            fail("Invalid NuGet package path: " + package)
        archive = parts[0] + "." + parts[1] + ".nupkg"
        destination = "packages/" + package
        local = ctx.path(ctx.attr.cache + "/" + package + "/" + archive)
        urls = (["file://" + str(local)] if local.exists else []) + ["https://api.nuget.org/v3-flatcontainer/" + package + "/" + archive]
        pin = pins.get(package)
        if pin and pin.get("restoreContentHash") != digest:
            fail("NuGet restore hash differs from qualified pin: " + package)
        ctx.download(url = urls, output = destination + "/" + archive, sha256 = pin["archiveSha256"] if pin else "", integrity = "" if pin else "sha512-" + digest, canonical_id = package + ":" + digest)
        checksum = ctx.execute(["/usr/bin/shasum", "-a", "512", str(ctx.path(destination + "/" + archive))])
        if checksum.return_code:
            fail("Cannot hash NuGet archive: " + checksum.stderr)
        archive_digest = _base64(checksum.stdout.split(" ")[0])
        ctx.extract(destination + "/" + archive, output = destination)
        ctx.file(destination + "/.nupkg.metadata", json.encode({"version": 2, "contentHash": digest, "source": "https://api.nuget.org/v3/index.json"}), executable = False)
        ctx.file(destination + "/" + archive + ".sha512", archive_digest, executable = False)

        # NuGet normalizes nuspec names even when the ZIP preserves case.
        for path in ctx.path(destination).readdir():
            if path.basename.lower().endswith(".nuspec") and path.basename != path.basename.lower():
                temporary = destination + "/normalized-nuspec.tmp"
                ctx.rename(path, temporary)
                ctx.rename(temporary, destination + "/" + path.basename.lower())
    ctx.file("BUILD.bazel", 'filegroup(name="files", srcs=glob(["packages/**"], allow_empty=True), visibility=["//visibility:public"])\n')

nuget_archives = repository_rule(implementation = _nuget, attrs = {"cache": attr.string(mandatory = True), "packages": attr.string(mandatory = True), "policy": attr.label(mandatory = True)})

def _checkout(ctx):
    names = []
    for path in ctx.attr.files:
        if path.startswith("/") or ".." in path.split("/"):
            fail("Invalid checkout input path")
        name = "workspace/" + path
        ctx.symlink(ctx.attr.root + "/" + path, name)
        names.append(name)
    ctx.file("BUILD.bazel", "exports_files(" + repr(names) + ")\n")

checkout_inputs = repository_rule(implementation = _checkout, attrs = {"root": attr.string(mandatory = True), "files": attr.string_list()}, local = True)
