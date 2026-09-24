"""Local SDK repository used by the explicit MSBuild toolchain."""

def _sdk_impl(ctx):
    ctx.symlink(ctx.attr.path, "sdk")
    for index, path in enumerate(ctx.attr.external_imports):
        if not ctx.attr.path.startswith("/nix/store/") or not path.startswith("/nix/store/") or ".." in path.split("/"):
            fail("external_imports require explicit Nix SDK import paths")
        ctx.symlink(path, "imports/" + str(index))
    roots = ctx.attr.runtime_roots
    if ctx.attr.include_runtime_closure:
        if not ctx.attr.path.startswith("/nix/store/"):
            fail("runtime closure requires a Nix SDK")
        result = ctx.execute(["/nix/var/nix/profiles/default/bin/nix-store", "-qR", str(ctx.path(ctx.attr.path).dirname.dirname)])
        if result.return_code:
            fail("Cannot resolve SDK runtime closure: " + result.stderr)
        roots = sorted([p for p in result.stdout.split("\n") if p])
    ctx.file("runtime-roots.json", json.encode(roots))
    for index, path in enumerate(roots):
        if not path.startswith("/nix/store/") or ".." in path.split("/"):
            fail("runtime_roots require explicit Nix store roots")
        ctx.symlink(path, "runtime/" + str(index))
    patterns = (["runtime/**"] if roots else []) + ["sdk/**"] + (["imports/**"] if ctx.attr.external_imports else [])
    ctx.file("BUILD.bazel", 'filegroup(name="files", srcs=glob(' + json.encode(patterns) + ', exclude=["sdk/**/BUILD", "sdk/**/BUILD.bazel"], allow_empty=False), visibility=["//visibility:public"])\nexports_files(["sdk/dotnet", "runtime-roots.json"])\n')

local_dotnet_sdk = repository_rule(
    implementation = _sdk_impl,
    attrs = {"path": attr.string(mandatory = True), "external_imports": attr.string_list(default = []), "runtime_roots": attr.string_list(default = []), "include_runtime_closure": attr.bool(default = False)},
    local = True,
)
