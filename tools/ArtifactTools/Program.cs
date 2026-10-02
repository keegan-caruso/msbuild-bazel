using System.Text.Json;

internal static class Program
{
    internal static readonly JsonSerializerOptions Json = new() { PropertyNameCaseInsensitive = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true };
    private static T Read<T>(string path) => JsonSerializer.Deserialize<T>(File.ReadAllText(path), Json)!;
    internal static string Safe(string value)
    {
        if (string.IsNullOrEmpty(value) || Path.IsPathRooted(value) || value.Contains('\\') || value.Split('/').Any(p => p is "" or "." or "..") || value.IndexOfAny(['\0', '\r', '\n']) >= 0)
        {
            throw new InvalidDataException("Unsafe logical path: " + value);
        }

        return value;
    }
    internal static void Copy(string source, string target)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        if (File.Exists(target))
        {
            if (!File.ReadAllBytes(source).AsSpan().SequenceEqual(File.ReadAllBytes(target)))
            {
                throw new InvalidDataException("Conflicting runtime/input destination: " + target);
            }

            return;
        }
        File.Copy(source, target);
    }
    public static int Main(string[] args)
    {
        try
        {
            if (args is ["graph-output", var graphOutput])
            {
                GraphOutputs.Export(Read<GraphOutputRequest>(graphOutput));
                return 0;
            }
            if (args is ["layout", var layout, var manifest] && manifest.StartsWith('@'))
            {
                ArtifactLayouts.Compose(Read<LayoutRequest>(layout), manifest[1..]);
                return 0;
            }
            if (args is ["extract", var extraction])
            {
                Package.Extract(Read<PackageRequest>(extraction));
                return 0;
            }
            if (args is ["native-toolchain", var nativeExtraction])
            {
                NativeToolchain.Extract(Read<NativeToolchainRequest>(nativeExtraction));
                return 0;
            }
            if (args is ["native-toolchain-packages", var nativePackages])
            {
                NativeToolchainPackages.Assemble(Read<NativeToolchainPackagesRequest>(nativePackages));
                return 0;
            }
            if (args.Length >= 2 && args[0] == "run")
            {
                return ApplicationLaunch.Run(Read<Launch>(args[1]), args[2..]);
            }

            throw new ArgumentException("Expected layout/extract/native-toolchain/native-toolchain-packages/run request.json");
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
