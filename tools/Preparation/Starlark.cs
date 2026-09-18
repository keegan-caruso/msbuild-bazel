using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

internal static class Starlark
{
    public static string Value(JsonNode? node) => node switch
    {
        JsonObject map => "{" + string.Join(", ", map.OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => Json.Text(JsonValue.Create(p.Key)) + ": " + Value(p.Value))) + "}",
        JsonArray array => "[" + string.Join(", ", array.Select(Value)) + "]",
        null => "None",
        JsonValue scalar when scalar.TryGetValue<bool>(out var boolean) => boolean ? "True" : "False",
        _ => Json.Text(node)
    };
    public static string Call(string rule, JsonObject attributes) => "\n" + rule + "(\n" + string.Concat(attributes.OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => "    " + p.Key + " = " + Value(p.Value) + ",\n")) + ")\n";
}
