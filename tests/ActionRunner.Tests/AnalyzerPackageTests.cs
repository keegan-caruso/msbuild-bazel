using ActionRunner;

internal static class AnalyzerPackageTests
{
    public static void Run(ActionRequest template, string temporary)
    {
        var workspace = Path.Combine(temporary, "analyzer-workspace");
        Directory.CreateDirectory(Path.Combine(workspace, "App", "obj"));
        File.WriteAllText(Path.Combine(workspace, "App", "App.csproj"),
            "<Project><ItemGroup><PackageReference Include=\"Fixture\" Version=\"[1.0.0]\" /></ItemGroup></Project>");
        JsonFiles.Write(Path.Combine(workspace, "App", "obj", "project.assets.json"),
            new RestoreAssets(new Dictionary<string, RestoreLibrary> { ["Fixture/1.0.0"] = new("package", "fixture/1.0.0") }));
        var source = Path.Combine(temporary, "analyzer-payload");
        File.WriteAllText(source, "original");
        var manifestPath = Path.Combine(temporary, "analyzer-manifest.json");
        const string path = "analyzers/dotnet/cs/Fixture.dll";
        var packageFile = new PackageFile(path, new FileInfo(source).Length, Files.Hash(source));
        var package = new Package("Fixture", "1.0.0", "fixture/1.0.0", [packageFile]);
        JsonFiles.Write(manifestPath, new PackageManifest(1, [package]));
        var request = template with
        {
            GraphProject = "App/App.csproj",
            PackageManifest = manifestPath,
            Packages = [new InputFile(source, package.Path + "/" + path)]
        };
        PackageInputs.Stage(request, workspace);
        File.WriteAllText(source, "modified");
        Reject(() => PackageInputs.Stage(request, workspace), "package payload hash mismatch");
        File.Delete(source);
        try { PackageInputs.Stage(request, workspace); }
        catch (FileNotFoundException error) when (error.Message.StartsWith("package payload missing:", StringComparison.Ordinal))
        {
            File.WriteAllText(source, "original");
        }
        if (!File.Exists(source)) throw new InvalidOperationException("missing analyzer payload was accepted");
        foreach (var invalid in new[] { "analyzers/dotnet/roslyn4.0/cs/Fixture.dll", "analyzers/dotnet/cs/tool.sh", "tools/Fixture.dll" })
        {
            JsonFiles.Write(manifestPath, new PackageManifest(1, [package with { Files = [packageFile with { Path = invalid }] }]));
            Reject(() => PackageInputs.Stage(request, workspace), "unsupported graph package payload category");
        }
    }

    private static void Reject(Action action, string diagnostic)
    {
        try { action(); }
        catch (InvalidDataException error) when (error.Message.StartsWith(diagnostic, StringComparison.Ordinal)) { return; }
        throw new InvalidOperationException("expected " + diagnostic);
    }
}
