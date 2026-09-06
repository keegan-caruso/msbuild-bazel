using System.Text.Json;

// Keep the graph manifest contract explicit without changing request parsing semantics.
internal static class JsonSerializer
{
    public static T? Deserialize<T>(string json, JsonSerializerOptions options) =>
        System.Text.Json.JsonSerializer.Deserialize<T>(json, options);

    public static string Serialize<T>(T value, JsonSerializerOptions options)
    {
        var configured = new JsonSerializerOptions(options)
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        };
        return System.Text.Json.JsonSerializer.Serialize(value, configured);
    }

    public static string Serialize<T>(T value) =>
        System.Text.Json.JsonSerializer.Serialize(value);
}
