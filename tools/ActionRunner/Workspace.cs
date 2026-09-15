using System.Text;

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
        if (request.GraphProject is not null && Directory.Exists(Output) &&
            Directory.EnumerateFileSystemEntries(Output).Any())
            throw new InvalidDataException("graph output already contains a prior attempt; use a fresh output");
        // Scratch must be under a declared output for the native sandbox to allow writes.
        Scratch = Path.Combine(Output, "work-" + Guid.NewGuid().ToString("N"));
        // .NET's macOS debugger transport uses a 260-byte path buffer. Reserve
        // 52 bytes for the separator, pipe prefix, PID, disambiguation key,
        // direction suffix and terminator; truncation can alias startup pipes
        // and hang a compiler before managed code runs.
        if (OperatingSystem.IsMacOS() && Encoding.UTF8.GetByteCount(Scratch) > 208)
            throw new InvalidDataException("action temporary path exceeds the macOS .NET pipe limit; use a shorter Bazel --output_base and output directory");
        Directory.CreateDirectory(Output);
        Directory.CreateDirectory(Diagnostics);
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
