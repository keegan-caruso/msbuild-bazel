using System.Text.Json.Nodes;

internal static class StaticWebAssetsTests
{
    internal static void Run()
    {
        var sdk = Path.Combine(Path.GetDirectoryName(Environment.ProcessPath!)!, "sdk/10.0.400");
        System.Runtime.Loader.AssemblyLoadContext.Default.Resolving += (context, name) =>
        {
            var candidate = Path.Combine(sdk, name.Name + ".dll");
            return File.Exists(candidate) ? context.LoadFromAssemblyPath(candidate) : null;
        };
        var root = Directory.CreateTempSubdirectory("static-web-assets-");
        try
        {
            // Captured from the pinned SDK's real Orchard Queries build.
            const string workspace = "/private/tmp/orchard-pilot-upstream";
            const string manifest = """
                {"Version":1,"Hash":"vWJr65I+JWmqGizCWhZhJ/MjPuxXzXVCBinHBL32bGU=","Source":"OrchardCore.Queries","BasePath":"_content/OrchardCore.Queries","Mode":"Default","ManifestType":"Build","ReferencedProjectsConfiguration":[],"DiscoveryPatterns":[{"Name":"OrchardCore.Queries/wwwroot","Source":"OrchardCore.Queries","ContentRoot":"/private/tmp/orchard-pilot-upstream/src/OrchardCore.Modules/OrchardCore.Queries/wwwroot/","BasePath":"_content/OrchardCore.Queries","Pattern":"**"}],"Assets":[],"Endpoints":[]}
                """;
            var source = Path.Combine(root.FullName, "staticwebassets.build.json");
            var portable = Path.Combine(root.FullName, "portable/staticwebassets.build.json");
            var restored = Path.Combine(root.FullName, "restored/staticwebassets.build.json");
            var second = Path.Combine(root.FullName, "second/staticwebassets.build.json");
            File.WriteAllText(source, manifest);
            StaticWebAssets.Capture(source, portable, workspace);
            StaticWebAssets.Restore(portable, restored, workspace);
            if (!JsonNode.DeepEquals(JsonNode.Parse(manifest), JsonNode.Parse(File.ReadAllText(restored)))) throw new Exception("SDK manifest round trip changed");
            StaticWebAssets.Restore(portable, restored, "/different/worker");
            StaticWebAssets.Capture(restored, second, "/different/worker");
            if (File.ReadAllText(portable) != File.ReadAllText(second)) throw new Exception("Static asset manifests depend on worker paths");
            File.WriteAllText(source, manifest.Replace("OrchardCore.Queries/wwwroot", "changed/wwwroot", StringComparison.Ordinal));
            try { StaticWebAssets.Capture(source, second, workspace); throw new Exception("Corrupt manifest accepted"); }
            catch (InvalidDataException) { }
            if (!StaticWebAssets.Intermediate("App/App.csproj", "net10.0", "App/obj/Release/net10.0/staticwebassets.development.json") ||
                StaticWebAssets.Intermediate("App/App.csproj", "net10.0", "Other/obj/Release/net10.0/staticwebassets.development.json")) throw new Exception("Static asset output ownership differs");
        }
        finally { root.Delete(true); }
    }
}
