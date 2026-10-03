using System.Text.Json;

namespace RulesMSBuild.GraphBuild;

// A graph's staged inputs are private scratch. Publish only the output ownership
// already validated by the child, keeping bytes and modes through same-volume moves.
internal static class GraphPublication
{
    internal static void Publish(string contractPath, string staging, string output)
    {
        var contract = JsonSerializer.Deserialize<GraphContract>(File.ReadAllText(contractPath))
            ?? throw new InvalidDataException("Missing graph publication contract");
        var projects = contract.Projects.Values;
        var directories = projects.SelectMany(project => project.OutputDirectories
            .Concat((project.Configurations ?? []).SelectMany(configuration => configuration.OutputDirectories)))
            .Distinct().OrderBy(path => path.Length).ThenBy(path => path, StringComparer.Ordinal).ToArray();
        var roots = new List<string>();
        foreach (var directory in directories)
        {
            if (!roots.Any(parent => directory.StartsWith(parent + "/", StringComparison.Ordinal)))
            {
                roots.Add(directory);
            }
        }
        var files = projects.SelectMany(project => (project.OutputFiles ?? [])
            .Concat((project.Configurations ?? []).SelectMany(configuration => configuration.OutputFiles ?? [])))
            .Distinct().Where(path => !roots.Any(directory => path.StartsWith(directory + "/", StringComparison.Ordinal))).ToArray();
        var source = new ContractFiles(Path.Combine(staging, "workspace"), staging);
        var destination = new ContractFiles(Path.Combine(output, "workspace"), output);
        Directory.CreateDirectory(destination.Root);
        foreach (var relative in roots)
        {
            var path = source.Resolve(relative);
            if (Directory.Exists(path))
            {
                var target = destination.Resolve(relative);
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                Directory.Move(path, target);
            }
        }
        foreach (var relative in files)
        {
            var path = source.Resolve(relative);
            if (File.Exists(path))
            {
                var target = destination.Resolve(relative);
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                File.Move(path, target);
            }
        }
        foreach (var name in new[] { "report.json", "report.binlog" })
        {
            var path = Path.Combine(staging, name);
            if (File.Exists(path))
            {
                File.Move(path, Path.Combine(output, name));
            }
        }
    }
}
