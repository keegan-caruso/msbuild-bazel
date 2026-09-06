namespace ActionRunner;

// Experimental private runtime, not relocation of the SDK or its native closure.
internal static class LoaderRuntime
{
    public static string Stage(ActionRequest request, Workspace workspace)
    {
        if (request.LoaderJit is null && request.LoaderManifest is null)
            return workspace.Dotnet;
        if (request.LoaderJit is null || request.LoaderManifest is null || request.NativeManifest is null)
            throw new InvalidDataException("loader JIT requires payload, manifest and native closure");
        var expected = JsonFiles.Read<Artifact>(request.LoaderManifest);
        var library = OperatingSystem.IsMacOS() ? "libclrjit.dylib" : "libclrjit.so";
        if (expected.Path != library)
            throw new InvalidDataException("loader JIT manifest name mismatch");
        Files.Verify(request.LoaderJit, expected.Size, expected.Sha256, "loader JIT payload mismatch");
        var root = Path.Combine(workspace.Scratch, "runtime");
        Directory.CreateDirectory(root);
        Files.Copy(workspace.Dotnet, Path.Combine(root, "dotnet"));
        Files.CopyTree(Path.Combine(workspace.SdkRoot, "host"), Path.Combine(root, "host"));
        var framework = Path.Combine("shared", "Microsoft.NETCore.App", "10.0.0");
        Files.CopyTree(Path.Combine(workspace.SdkRoot, framework), Path.Combine(root, framework));
        var jit = Path.Combine(root, framework, library);
        // Nix payloads retain read-only modes when copied. Unlink our private
        // copy before replacement; never change permissions on the store file.
        File.Delete(jit);
        Files.Copy(request.LoaderJit, jit);
        // SDK, packs and other tool data remain declared, absolute-path inputs.
        foreach (var directory in Directory.EnumerateDirectories(workspace.SdkRoot))
        {
            var name = Path.GetFileName(directory);
            if (name is not "host" and not "shared")
                Directory.CreateSymbolicLink(Path.Combine(root, name), directory);
        }
        JsonFiles.Write(Path.Combine(workspace.Diagnostics, "loader-runtime.json"), new
        {
            dotnet = Path.Combine(root, "dotnet"), jitPath = jit,
            originalJitPath = Path.Combine(workspace.SdkRoot, framework, library),
            sha256 = Files.Hash(jit)
        });
        return Path.Combine(root, "dotnet");
    }
}
