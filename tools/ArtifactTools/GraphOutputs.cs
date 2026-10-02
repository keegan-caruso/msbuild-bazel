using System.Text.Json;

internal sealed record GraphOutputRequest(string Contract, string Workspace, string Path, string Output);
internal sealed record OutputContract(Dictionary<string, OutputDeclaration> Projects);
internal sealed record OutputDeclaration(string[]? OutputDirectories = null, string[]? OutputFiles = null, OutputDeclaration[]? Configurations = null);

internal static class GraphOutputs
{
    internal static void Export(GraphOutputRequest request)
    {
        var path = Program.Safe(request.Path);
        var contract = JsonSerializer.Deserialize<OutputContract>(File.ReadAllText(request.Contract), Program.Json) ?? throw new InvalidDataException("Missing graph output contract");
        var declarations = contract.Projects.Values.SelectMany(project => new[] { project }.Concat(project.Configurations ?? []));
        var owned = declarations.Any(project => (project.OutputFiles ?? []).Any(file => path == Program.Safe(file)) ||
            (project.OutputDirectories ?? []).Any(directory => path.StartsWith(Program.Safe(directory) + "/", StringComparison.Ordinal)));
        if (!owned)
        {
            throw new InvalidDataException("Graph output is not declared: " + path);
        }
        var source = Path.Combine(request.Workspace, path);
        if (!File.Exists(source))
        {
            throw new InvalidDataException("Missing graph output: " + path);
        }
        Program.Copy(source, request.Output);
    }
}
