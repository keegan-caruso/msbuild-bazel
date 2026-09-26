using System.Globalization;
using System.Text;
using System.Text.Json;

namespace RulesMSBuild.ProjectSync;

// JSON string escapes (notably \uXXXX) are not accepted by Bazel 8/9.
internal static class StarlarkLiteral
{
    internal static string Serialize<T>(T value) => Write(JsonSerializer.SerializeToElement(value));

    private static string Write(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.Object => "{" + string.Join(",", value.EnumerateObject().Select(p => Quote(p.Name) + ":" + Write(p.Value))) + "}",
        JsonValueKind.Array => "[" + string.Join(",", value.EnumerateArray().Select(Write)) + "]",
        JsonValueKind.String => Quote(value.GetString()!),
        JsonValueKind.True => "True",
        JsonValueKind.False => "False",
        JsonValueKind.Null => "None",
        JsonValueKind.Number => value.GetRawText(),
        _ => throw new InvalidDataException("Unsupported Starlark literal")
    };

    private static string Quote(string value)
    {
        var result = new StringBuilder("\"");
        foreach (var character in value)
        {
            result.Append(character switch
            {
                '"' => "\\\"",
                '\\' => "\\\\",
                '\n' => "\\n",
                '\r' => "\\r",
                '\t' => "\\t",
                '\b' => "\\b",
                '\f' => "\\f",
                < ' ' or '\u007f' => "\\x" + ((int)character).ToString("x2", CultureInfo.InvariantCulture),
                _ => character.ToString()
            });
        }
        return result.Append('"').ToString();
    }
}
