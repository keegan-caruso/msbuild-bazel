using System.Diagnostics;

namespace RulesMSBuild.GraphBuild;

internal static class Restore
{
    internal static GraphContract Run(GraphContract contract, string root, string sdkRoot)
    {
        var owned = new[] { "RestoreSources", "RestoreConfigFile", "RestorePackagesPath", "RestoreFallbackFolders", "RestoreAdditionalProjectSources", "RestoreAdditionalProjectFallbackFolders" };
        if (contract.Properties.Keys.Any(key => owned.Contains(key, StringComparer.OrdinalIgnoreCase)))
        {
            throw new InvalidDataException("Graph Restore source, package and fallback paths are controlled by declared archives");
        }
        var packages = Path.Combine(root, ".nuget");
        var source = Path.Combine(root, ".package-source");
        Directory.CreateDirectory(source);
        if (contract.PackageDigests is not null && !Directory.GetFiles(source, "*.nupkg")
            .Select(ContractFiles.Digest).Order(StringComparer.Ordinal).SequenceEqual(contract.PackageDigests.Order(StringComparer.Ordinal)))
        {
            throw new InvalidDataException("Graph package set changed; run your graph-mode sync target before building");
        }
        using var packageSdks = RulesMSBuild.PackageSdks.Prepare(root);
        var config = Path.Combine(source, "NuGet.Config");
        File.WriteAllText(config, "<configuration><packageSources><clear/></packageSources><fallbackPackageFolders><clear/></fallbackPackageFolders></configuration>");
        foreach (var entry in contract.Entries ?? [contract.Entry])
        {
            var process = new ProcessStartInfo(Path.Combine(sdkRoot, OperatingSystem.IsWindows() ? "dotnet.exe" : "dotnet"))
            {
                WorkingDirectory = root,
                UseShellExecute = false,
            };
            foreach (var argument in new[] { "restore", Path.Combine(root, entry), "--configfile", config, "--source", source, "--packages", packages, "-p:NuGetAudit=false",
                "-p:RestoreFallbackFolders=", "-p:RestoreAdditionalProjectSources=", "-p:RestoreAdditionalProjectFallbackFolders=" })
            {
                process.ArgumentList.Add(argument);
            }
            // Restore each project's authored frameworks; the build graph still selects its requested framework.
            foreach (var (key, value) in contract.Properties.Where(property => !property.Key.Equals("TargetFramework", StringComparison.OrdinalIgnoreCase)))
            {
                process.ArgumentList.Add("-p:" + key + "=" + value);
            }
            using var child = Process.Start(process) ?? throw new InvalidOperationException("Could not start Restore");
            child.WaitForExit();
            if (child.ExitCode != 0)
            {
                throw new InvalidOperationException("Offline graph Restore failed");
            }
        }
        var packageFiles = Directory.Exists(packages) ? Directory.GetFiles(packages, "*", SearchOption.AllDirectories)
            .Select(path => Path.GetRelativePath(root, path)) : [];
        return contract with
        {
            SharedInputs = contract.SharedInputs.Concat(packageFiles).ToArray()
        };
    }
}
