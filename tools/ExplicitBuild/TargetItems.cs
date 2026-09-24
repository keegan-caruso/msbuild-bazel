using System.Text.Json;
using System.Xml;
using System.Xml.Linq;
using Microsoft.Build.Execution;

internal sealed record TargetInput(string File, string Target, string Type, string[] BeforeTargets);
internal sealed record TargetItem(string Identity, Dictionary<string, string> Metadata);

// Explicit scalar target results. File outputs require declared artifacts rather
// than serializing producer-local paths into a consumer's action.
internal static class TargetItems
{
    private static void Name(string value)
    {
        XmlConvert.VerifyNCName(value);
        if (value.StartsWith("_Bazel", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("Reserved target/item name: " + value);
        }
    }
    private static string Scalar(string value)
    {
        if (value.Contains('/') || value.Contains('\\') || value.Contains("$(", StringComparison.Ordinal) || value.Contains("@(", StringComparison.Ordinal))
        {
            throw new InvalidDataException("Target results must be scalar values, not paths or expressions: " + value);
        }

        return value;
    }
    internal static void Export(Session session, BuildResult result)
    {
        if (session.Request.TargetOutput is null)
        {
            return;
        }

        var outputs = new Dictionary<string, TargetItem[]>();
        foreach (var (target, names) in session.Request.TargetExports ?? new())
        {
            Name(target);
            foreach (var name in names)
            {
                Name(name);
            }

            outputs.Add(target, result.ResultsByTarget[target].Items.Select(item => new TargetItem(Scalar(item.ItemSpec),
                names.ToDictionary(name => name, name => Scalar(item.GetMetadata(name)), StringComparer.OrdinalIgnoreCase))).ToArray());
        }
        File.WriteAllText(Path.Combine(session.State, "targets.json"), JsonSerializer.Serialize(outputs, Program.Json));
    }
    internal static void Inject(Request request, XElement root)
    {
        var index = 0;
        foreach (var input in request.TargetInputs ?? [])
        {
            Name(input.Type);
            Name(input.Target);
            if (new[] { "Compile", "ProjectReference", "Reference", "Analyzer", "PackageReference", "PackageVersion", "FrameworkReference" }.Contains(input.Type, StringComparer.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("Target result items cannot replace dependency/source declarations");
            }

            foreach (var target in input.BeforeTargets)
            {
                Name(target);
            }

            var results = JsonSerializer.Deserialize<Dictionary<string, TargetItem[]>>(File.ReadAllText(input.File), Program.Json)!;
            if (!results.TryGetValue(input.Target, out var rows))
            {
                throw new InvalidDataException("Missing declared target result: " + input.Target);
            }

            var group = new XElement("ItemGroup");
            foreach (var row in rows)
            {
                var item = new XElement(input.Type, new XAttribute("Include", Program.Escape(Scalar(row.Identity))));
                foreach (var (name, value) in row.Metadata)
                {
                    Name(name);
                    item.Add(new XElement(name, Program.Escape(Scalar(value))));
                }
                group.Add(item);
            }
            if (input.BeforeTargets.Length == 0)
            {
                root.Add(group);
            }
            else
            {
                root.Add(new XElement("Target", new XAttribute("Name", "_BazelTargetItems" + index++), new XAttribute("BeforeTargets", string.Join(';', input.BeforeTargets)), group));
            }
        }
    }
}
