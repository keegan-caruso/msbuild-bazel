using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

internal sealed record RuntimeAssembly(string Project, string Framework, string Path);
internal sealed record RuntimeNative(string Label, string Path);
internal sealed record RuntimeLayoutRequest(string Output, string Shared, string FrameworkName, string Version,
    string TargetFramework, string TargetFrameworkMoniker, string RuntimeIdentifier, string BuildId, string BuildInfo,
    string GraphContract, Dictionary<string, RuntimeAssembly> Managed, Dictionary<string, RuntimeNative> Native, JsonObject Provenance);

internal static class RuntimeLayouts
{
    internal static void Compose(RuntimeLayoutRequest request, string manifest)
    {
        var shared = Program.Safe(request.Shared);
        var buildInfo = Program.Safe(request.BuildInfo);
        if (request.BuildId.Contains('\n') || request.BuildId.Contains('\r'))
        {
            throw new InvalidDataException("Runtime build ID must be one line");
        }
        ArtifactLayouts.Compose(new(request.Output), manifest);
        void Write(string path, string content)
        {
            var destination = Path.Combine(request.Output, Program.Safe(path));
            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            if (File.Exists(destination) && File.ReadAllText(destination) != content)
            {
                throw new InvalidDataException("Runtime metadata conflicts with producer output: " + path);
            }
            File.WriteAllText(destination, content);
        }
        void Json(string path, object value) => Write(path, JsonSerializer.Serialize(value, Program.Json) + "\n");
        var target = request.TargetFrameworkMoniker + "/" + request.RuntimeIdentifier;
        var identity = request.FrameworkName + ".Runtime." + request.RuntimeIdentifier + "/" + request.Version;
        var assets = new
        {
            runtime = request.Managed.Keys.Order(StringComparer.Ordinal).ToDictionary(name => name, _ => new { }),
            native = request.Native.Where(pair => pair.Value.Path.StartsWith(shared + "/", StringComparison.Ordinal))
                .ToDictionary(pair => pair.Key, _ => new { })
        };
        Json(shared + "/" + request.FrameworkName + ".deps.json", new
        {
            runtimeTarget = new
            {
                name = target,
                signature = ""
            },
            compilationOptions = new
            {
            },
            targets = new Dictionary<string, object>
            {
                [request.TargetFrameworkMoniker] = new { },
                [target] = new Dictionary<string, object> { [identity] = assets }
            },
            libraries = new Dictionary<string, object> { [identity] = new { type = "package", serviceable = false, sha512 = "" } }
        });
        Json(shared + "/" + request.FrameworkName + ".runtimeconfig.json", new
        {
            runtimeOptions = new
            {
                tfm = request.TargetFramework
            }
        });
        Write(shared + "/.version", request.BuildId + "\n" + request.Version + "\n");
        var provenance = request.Provenance.DeepClone().AsObject();
        provenance["framework"] = request.Version;
        provenance["platform"] = request.RuntimeIdentifier;
        provenance["managed"] = JsonSerializer.SerializeToNode(request.Managed, Program.Json);
        provenance["native"] = JsonSerializer.SerializeToNode(request.Native, Program.Json);
        using (var source = File.OpenRead(request.GraphContract))
        {
            provenance["graphContractSha256"] = Convert.ToHexString(SHA256.HashData(source)).ToLowerInvariant();
        }
        Json(buildInfo, provenance);
    }
}
