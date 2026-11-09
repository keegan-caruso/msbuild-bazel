using System.Diagnostics;
using System.Text.Json;
using RulesMSBuild.ProjectCache;

namespace RulesMSBuild.ProjectSync;

internal static class QualificationSeed
{
    internal static void Publish(BuildSeed evidence, string root, string sdk, string contract, QualificationOptions options)
    {
        var directory = QualificationSandbox.Base + "/output";
        var contractPath = Path.Combine(directory, "seed-contract.json");
        var evidencePath = Path.Combine(directory, "seed-proof.json");
        File.WriteAllText(contractPath, contract);
        File.WriteAllText(evidencePath, JsonSerializer.Serialize(evidence));
        var start = new ProcessStartInfo(Path.Combine(sdk, "dotnet")) { WorkingDirectory = root };
        foreach (var argument in new[] { Path.Combine(options.GraphRunner!, "GraphBuild.dll"), "seed", root, contractPath,
            Path.Combine(directory, "seed-report.json"), Path.Combine(options.Directory, "graph"), evidencePath })
        {
            start.ArgumentList.Add(argument);
        }
        start.Environment["RULES_MSBUILD_PROJECT_CACHE_URL"] = options.Url;
        start.Environment["RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN"] = options.BearerToken;
        start.Environment.Remove("RULES_MSBUILD_SYNC_PROFILE");
        using var process = Process.Start(start)!;
        process.WaitForExit();
        if (process.ExitCode != 0)
        {
            throw new InvalidDataException("Qualification products are incompatible with the ordinary graph context");
        }
    }
}
