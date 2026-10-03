using System.Text.Json;

internal sealed record GraphOutputRequest(string Contract, string Workspace, string Path, string Output, bool Directory = false, bool BazelInputs = false, bool Restore = false);
internal sealed record OutputContract(Dictionary<string, OutputDeclaration> Projects, RestoreOutputDeclaration? Restore = null);
internal sealed record RestoreOutputDeclaration(string[] Outputs);
internal sealed record OutputDeclaration(string[]? OutputDirectories = null, string[]? OutputFiles = null, OutputDeclaration[]? Configurations = null);

internal static class GraphOutputs
{
    internal static void Export(GraphOutputRequest request)
    {
        var path = Program.Safe(request.Path);
        var contract = JsonSerializer.Deserialize<OutputContract>(File.ReadAllText(request.Contract), Program.Json) ?? throw new InvalidDataException("Missing graph output contract");
        var declarations = contract.Projects.Values.SelectMany(project => new[] { project }.Concat(project.Configurations ?? [])).ToArray();
        var directories = request.Restore ? [] : declarations.SelectMany(project => project.OutputDirectories ?? []).Select(Program.Safe).ToArray();
        var files = (request.Restore ? contract.Restore?.Outputs ?? throw new InvalidDataException("Missing Restore output contract")
            : declarations.SelectMany(project => project.OutputFiles ?? [])).Select(Program.Safe).ToHashSet(StringComparer.Ordinal);
        bool Owned(string relative) => files.Contains(relative) || directories.Any(directory => relative.StartsWith(directory + "/", StringComparison.Ordinal));
        bool Tree(string relative) => directories.Any(directory => relative == directory || relative.StartsWith(directory + "/", StringComparison.Ordinal) || directory.StartsWith(relative + "/", StringComparison.Ordinal)) ||
            files.Any(file => file.StartsWith(relative + "/", StringComparison.Ordinal));
        var owned = request.Directory ? Tree(path) : Owned(path);
        if (!owned)
        {
            throw new InvalidDataException("Graph output is not declared: " + path);
        }
        var workspace = Path.TrimEndingDirectorySeparator(Path.GetFullPath(request.Workspace));
        var source = Path.Combine(workspace, path);
        if (!(request.Directory ? Directory.Exists(source) : File.Exists(source)))
        {
            throw new InvalidDataException("Missing graph output: " + path);
        }
        // Check every ancestor before opening a file or enumerating a directory.
        for (var current = source; current != workspace; current = System.IO.Path.GetDirectoryName(current)!)
        {
            RejectLink(current, request.BazelInputs && current == source && !request.Directory);
        }
        if (request.Directory)
        {
            CopyTree(source, request.Output, path, Owned, Tree, request.BazelInputs);
        }
        else
        {
            Program.Copy(source, request.Output);
        }
    }

    private static void RejectLink(string path, bool bazelFile = false)
    {
        if (File.GetAttributes(path).HasFlag(FileAttributes.ReparsePoint))
        {
            // Bazel materializes declared tree inputs as one-hop file links.
            // Graph producers verify their outputs before publication. Do not
            // follow a directory link or a second link in the original artifact.
            var target = bazelFile ? new FileInfo(path).ResolveLinkTarget(false) : null;
            if (target is FileInfo && target.Exists && target.LinkTarget is null)
            {
                return;
            }
            throw new InvalidDataException("Graph output contains a link: " + path);
        }
    }

    private static void CopyTree(string source, string target, string relative, Func<string, bool> owned, Func<string, bool> tree, bool bazelInputs)
    {
        Directory.CreateDirectory(target);
        foreach (var path in Directory.EnumerateFileSystemEntries(source))
        {
            RejectLink(path, bazelInputs && !Directory.Exists(path));
            var destination = System.IO.Path.Combine(target, System.IO.Path.GetFileName(path));
            var child = relative + "/" + System.IO.Path.GetFileName(path);
            if (Directory.Exists(path))
            {
                if (!tree(child))
                {
                    throw new InvalidDataException("Graph output is not declared: " + child);
                }
                CopyTree(path, destination, child, owned, tree, bazelInputs);
            }
            else
            {
                if (!owned(child))
                {
                    throw new InvalidDataException("Graph output is not declared: " + child);
                }
                Program.Copy(path, destination);
            }
        }
    }
}
