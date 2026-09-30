namespace RulesMSBuild.GraphBuild;

internal static class GraphTools
{
    internal static GraphContract Bind(GraphContract contract, string root, string sdk)
    {
        var properties = new Dictionary<string, string>(contract.Properties, StringComparer.OrdinalIgnoreCase);
        var inputs = new HashSet<string>(contract.SharedInputs, StringComparer.Ordinal);
        var files = new ContractFiles(root, sdk);
        if (contract.ToolProperties?.Count > 0 || File.Exists(Path.Combine(root, ".graph-tools/bindings.json")))
        {
            var declared = System.Text.Json.JsonSerializer.Deserialize<Dictionary<string, string>>(
                File.ReadAllText(files.Resolve(".graph-tools/bindings.json"))) ?? [];
            if (declared.Count != contract.ToolProperties?.Count || declared.Any(pair =>
                !contract.ToolProperties.TryGetValue(pair.Key, out var value) || value != pair.Value))
            {
                throw new InvalidDataException("Graph tool bindings changed; rerun sync");
            }
        }
        foreach (var (name, path) in contract.ToolProperties ?? [])
        {
            System.Xml.XmlConvert.VerifyNCName(name);
            if (name.StartsWith("MSBuild", StringComparison.OrdinalIgnoreCase) || name.StartsWith("Restore", StringComparison.OrdinalIgnoreCase) ||
                name.StartsWith("_Bazel", StringComparison.OrdinalIgnoreCase) || name.Equals("PathMap", StringComparison.OrdinalIgnoreCase) ||
                name.Equals("UseSharedCompilation", StringComparison.OrdinalIgnoreCase) || name.Equals("NetCoreSdkRoot", StringComparison.OrdinalIgnoreCase) || name.Equals("DOTNET_HOST_PATH", StringComparison.OrdinalIgnoreCase) || properties.ContainsKey(name))
            {
                throw new InvalidDataException("Reserved or conflicting graph tool property: " + name);
            }
            if (!path.StartsWith(".graph-tools/", StringComparison.Ordinal) || path.Split('/').Length < 3)
            {
                throw new InvalidDataException("Graph tool entry must use its declared closure: " + path);
            }
            var entry = files.Resolve(path);
            if (!File.Exists(entry))
            {
                throw new InvalidDataException("Missing graph tool entry: " + path);
            }
            properties.Add(name, entry);
            var directory = files.Resolve(string.Join('/', path.Split('/').Take(2)));
            foreach (var file in Directory.EnumerateFiles(directory, "*", SearchOption.AllDirectories))
            {
                var relative = Path.GetRelativePath(root, file);
                files.Resolve(relative);
                inputs.Add(relative);
            }
        }
        return contract with
        {
            Properties = properties,
            SharedInputs = inputs.Order(StringComparer.Ordinal).ToArray(),
            Restore = contract.Restore is null ? null : contract.Restore with
            {
                Inputs = contract.Restore.Inputs.Concat(inputs.Except(contract.SharedInputs)).Distinct().Order(StringComparer.Ordinal).ToArray()
            }
        };
    }
}
