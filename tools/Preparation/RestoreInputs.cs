using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace RulesMSBuild.Preparation;

internal static class RestoreInputs
{
    public static string Normalize(string text, string source, string cache, string name)
    {
        var replacements = new Dictionary<string, string> { [source] = "${WORKSPACE}" };
        if (cache != source) replacements[cache] = "${WORKSPACE}/.nuget/packages";
        var expression = new Regex("(" + string.Join("|", replacements.Keys.OrderByDescending(key => key.Length).Select(Regex.Escape)) + ")(?=/|[\"'<\\s]|$)");
        text = expression.Replace(text, match => replacements[match.Value]);
        if (Path.GetFileName(name) == "project.nuget.cache")
        {
            var receipt = JsonNode.Parse(text)!;
            if (receipt["success"]?.GetValue<bool>() != true) throw new InvalidDataException("Unsuccessful restore");
            if (receipt.AsObject().ContainsKey("dgSpecHash")) receipt["dgSpecHash"] = "$NORMALIZED";
            text = Json.Canonical(receipt);
        }
        return text;
    }
    public static void Run(JsonNode request)
    {
        foreach (var input in request.Array("files"))
        {
            var output = input!.String("output"); Directory.CreateDirectory(Path.GetDirectoryName(output)!);
            File.WriteAllText(output, Normalize(File.ReadAllText(input.String("source")), request.String("workspace"), request.String("cache"), input.String("name")));
        }
    }
}
