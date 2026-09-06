namespace ActionRunner;

internal sealed class Workspace
{
    public string Output { get; }
    public string Diagnostics { get; }
    public string Scratch { get; }
    public string Root { get; }
    public string Dotnet { get; }
    public string SdkRoot => Path.GetDirectoryName(Dotnet)!;

    public Workspace(ActionRequest request)
    {
        Output = Path.GetFullPath(request.Output);
        Diagnostics = Path.GetFullPath(request.Diagnostics);
        Directory.CreateDirectory(Output);
        Directory.CreateDirectory(Diagnostics);
        // Scratch must be under a declared output for the native sandbox to allow writes.
        Scratch = Path.Combine(Output, "work-" + Guid.NewGuid().ToString("N"));
        Root = Path.Combine(Scratch, "workspace");
        Directory.CreateDirectory(Root);
        // The loaded host resolves sandbox symlinks, keeping restore SDK paths and MSBuild aligned.
        Dotnet = Environment.ProcessPath ?? throw new InvalidOperationException("cannot locate the .NET host");
    }

    public void Stage(ActionRequest request)
    {
        if (!string.IsNullOrEmpty(request.UndeclaredProbe)) File.ReadAllText(request.UndeclaredProbe);
        foreach (var source in request.Sources)
            Files.Copy(source.Source, Path.Combine(Root, source.Destination));
        foreach (var restore in request.Restore)
            foreach (var (relative, contents) in JsonFiles.Read<Dictionary<string, string>>(restore))
            {
                var target = Path.Combine(Root, relative);
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                File.WriteAllText(target, contents.Replace("${WORKSPACE}", Root).Replace("${SDK}", SdkRoot));
            }
    }

}
