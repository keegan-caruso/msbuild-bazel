using ActionRunner;

internal static class PilotPackageTests
{
    public static void Run(ActionRequest template, string source, string staged, string temporary)
    {
        var workspace = Path.Combine(temporary, "workspace");
        const string project = "src/Serilog/Serilog.csproj";
        foreach (var path in new[] { project, "src/Serilog/obj/project.assets.json" })
            Files.Copy(Path.Combine(source, path), Path.Combine(workspace, path));
        var originalManifest = Directory.GetFiles(Path.Combine(staged, "package-manifests"), "*.json").Single();
        var manifest = JsonFiles.Read<PackageManifest>(originalManifest);
        var localManifest = Path.Combine(temporary, "packages.json");
        JsonFiles.Write(localManifest, manifest);
        var inputs = manifest.Packages.SelectMany(package => package.Files.Select(file =>
        {
            var relative = package.Path + "/" + file.Path;
            var link = Path.Combine(temporary, "links", relative);
            Directory.CreateDirectory(Path.GetDirectoryName(link)!);
            File.CreateSymbolicLink(link, Path.Combine(staged, "packages", relative));
            return new InputFile(link, relative);
        })).ToArray();
        var request = template with { GraphProject = project, PackageManifest = localManifest, Packages = inputs };
        PackageInputs.Stage(request, workspace); // Every input, including the pinned archive, is a symlink.
        var assetsPath = Path.Combine(workspace, "src/Serilog/obj/project.assets.json");
        var originalAssets = File.ReadAllText(assetsPath);
        var assets = JsonFiles.Read<RestoreAssets>(assetsPath);
        assets.Libraries["PolySharp/1.15.0"] = assets.Libraries["PolySharp/1.15.0"] with { Sha512 = "changed" };
        JsonFiles.Write(assetsPath, assets);
        Reject(() => PackageInputs.Stage(request, workspace), "qualified package restore content hash mismatch");
        File.WriteAllText(assetsPath, originalAssets);
        var package = manifest.Packages.Single(p => p.Id == "PolySharp");
        var altered = package with { Files = package.Files.Select(file => file.Path.EndsWith("PolySharp.SourceGenerators.dll") ? file with { Sha256 = new string('0', 64) } : file).ToArray() };
        JsonFiles.Write(localManifest, manifest with { Packages = manifest.Packages.Select(p => p == package ? altered : p).ToArray() });
        Reject(() => PackageInputs.Stage(request, workspace), "qualified package manifest differs from pinned archive");
        JsonFiles.Write(localManifest, manifest);
        var archive = inputs.Single(input => input.Destination.EndsWith("polysharp.1.15.0.nupkg"));
        File.Delete(archive.Source);
        File.WriteAllText(archive.Source, "repacked payload");
        Reject(() => PackageInputs.Stage(request, workspace), "qualified package archive hash mismatch");
    }

    private static void Reject(Action action, string diagnostic)
    {
        try { action(); }
        catch (InvalidDataException error) when (error.Message == diagnostic) { return; }
        throw new InvalidOperationException("expected " + diagnostic);
    }
}
