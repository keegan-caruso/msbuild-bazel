using System.Text.Json;
using ActionRunner;

internal static class AssetRoleTests
{
    public static void Run()
    {
        using (var mixed = JsonDocument.Parse("""{"targets":{"net10.0":{"Example/1.0.0":{}},"netstandard2.0":{"Example/1.0.0":{"native":{"payload":{}}}}}}"""))
        {
            PackageInputs.VerifyAssetRoles(mixed.RootElement, "Example/1.0.0", null, "net10.0");
            try
            {
                PackageInputs.VerifyAssetRoles(mixed.RootElement, "Example/1.0.0", null, "netstandard2.0");
                throw new InvalidOperationException("selected unsupported asset role accepted");
            }
            catch (InvalidDataException) { }
        }
        foreach (var (identity, role, allowed) in new[] {
            ("RulesMsbuild.Unknown/1.0.0", "runtimeTargets", false),
            ("PolySharp/1.15.0", "resource", false),
            ("System.Management/6.0.1", "runtimeTargets", true),
            ("Microsoft.TestPlatform.TestHost/17.11.1", "resource", true) })
        {
            using var document = JsonDocument.Parse("{\"targets\":{\"net10.0\":{\"" + identity + "\":{\"" + role + "\":{\"payload.dll\":{}}}}}}");
            try
            {
                PackageInputs.VerifyAssetRoles(document.RootElement, identity, PilotPackagePolicy.Find(identity));
                if (!allowed) throw new InvalidOperationException("unqualified asset role accepted");
            }
            catch (InvalidDataException) when (!allowed) { }
        }
    }
}
