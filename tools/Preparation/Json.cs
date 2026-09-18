using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

internal static class Json
{
    private static readonly IComparer<string> KeyOrder = Comparer<string>.Create((left, right) =>
    {
        var a = left.EnumerateRunes().GetEnumerator();
        var b = right.EnumerateRunes().GetEnumerator();
        while (a.MoveNext())
        {
            if (!b.MoveNext()) return 1;
            var compared = a.Current.Value.CompareTo(b.Current.Value);
            if (compared != 0) return compared;
        }
        return b.MoveNext() ? -1 : 0;
    });
    private static readonly JsonSerializerOptions Options = new() { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
    public static string String(this JsonNode? node, string key) => node?[key]?.GetValue<string>() ?? throw new InvalidDataException("Missing string: " + key);
    public static JsonArray Array(this JsonNode? node, string key) => node?[key] as JsonArray ?? throw new InvalidDataException("Missing array: " + key);
    public static string Text(JsonNode? value) => value?.ToJsonString(Options) ?? "null";
    public static string Sha(byte[] value) => Convert.ToHexStringLower(SHA256.HashData(value));
    public static string Digest(JsonNode value) => Sha(Encoding.UTF8.GetBytes(Canonical(value)));
    // Python's identity policy sorts keys and ASCII-escapes strings. Keep the
    // encoding explicit: System.Text.Json defaults are not this wire contract.
    public static string Canonical(JsonNode? value) => value switch
    {
        JsonObject map => "{" + string.Join(",", map.OrderBy(p => p.Key, KeyOrder).Select(p => Quote(p.Key) + ":" + Canonical(p.Value))) + "}",
        JsonArray list => "[" + string.Join(",", list.Select(Canonical)) + "]",
        JsonValue scalar when scalar.TryGetValue<string>(out var text) => Quote(text),
        _ => Text(value)
    };
    private static string Quote(string value)
    {
        var result = new StringBuilder("\"");
        foreach (var c in value)
        {
            result.Append(c switch
            {
                '"' => "\\\"",
                '\\' => "\\\\",
                '\b' => "\\b",
                '\f' => "\\f",
                '\n' => "\\n",
                '\r' => "\\r",
                '\t' => "\\t",
                < ' ' or > '~' => "\\u" + ((int)c).ToString("x4", CultureInfo.InvariantCulture),
                _ => c.ToString()
            });
        }
        return result.Append('"').ToString();
    }
    public static void Write(string path, JsonNode node) => File.WriteAllText(path, Text(node) + "\n");
    public static JsonNode Read(string path) => JsonNode.Parse(File.ReadAllText(path)) ?? throw new InvalidDataException("Empty JSON: " + path);
    public static JsonArray Strings(IEnumerable<string> values) => new(values.Select(v => (JsonNode?)JsonValue.Create(v)).ToArray());
}
