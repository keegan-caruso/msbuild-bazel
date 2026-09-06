using System.Text.Json;
using System.Text.Json.Serialization;

namespace ActionRunner;

internal static class JsonFiles
{
    private static readonly JsonSerializerOptions RequestOptions = CreateOptions(JsonNamingPolicy.SnakeCaseLower);
    private static readonly JsonSerializerOptions OutputOptions = CreateOptions(JsonNamingPolicy.CamelCase);

    private static JsonSerializerOptions CreateOptions(JsonNamingPolicy namingPolicy)
    {
        var options = new JsonSerializerOptions
        {
            PropertyNamingPolicy = namingPolicy,
            WriteIndented = true,
            RespectRequiredConstructorParameters = true,
            RespectNullableAnnotations = true,
            AllowDuplicateProperties = false
        };
        options.Converters.Add(new JsonStringEnumConverter<ProjectKind>(allowIntegerValues: false));
        options.MakeReadOnly(populateMissingResolver: true);
        return options;
    }

    public static ActionRequest ReadRequest(string path) => Read<ActionRequest>(path, RequestOptions);

    public static T Read<T>(string path) => Read<T>(path, OutputOptions);

    private static T Read<T>(string path, JsonSerializerOptions options)
    {
        using var stream = File.OpenRead(path);
        return JsonSerializer.Deserialize<T>(stream, options) ?? throw new InvalidDataException("empty JSON: " + path);
    }

    public static void Write<T>(string path, T value)
    {
        using var stream = File.Create(path);
        JsonSerializer.Serialize(stream, value, OutputOptions);
        stream.WriteByte((byte)'\n');
    }
}
