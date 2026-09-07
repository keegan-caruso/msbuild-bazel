using ActionRunner;
using System.Text.Json;

internal static class AssetRoleTests
{
    public static void Run()
    {
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
