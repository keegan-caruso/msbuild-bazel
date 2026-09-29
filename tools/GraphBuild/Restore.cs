using System.Diagnostics;

namespace RulesMSBuild.GraphBuild;

internal static class Restore
{
    internal static GraphContract Run(GraphContract contract, string root, string sdkRoot)
    {
        var packages = Path.Combine(root, ".nuget");
        var source = Path.Combine(root, ".package-source");
        Directory.CreateDirectory(source);
        if (contract.PackageDigests is not null && !Directory.GetFiles(source, "*.nupkg")
            .Select(ContractFiles.Digest).Order(StringComparer.Ordinal).SequenceEqual(contract.PackageDigests.Order(StringComparer.Ordinal)))
        {
            throw new InvalidDataException("Graph package set changed; run your graph-mode sync target before building");
        }
        foreach (var entry in contract.Entries ?? [contract.Entry])
        {
            var process = new ProcessStartInfo(Path.Combine(sdkRoot, OperatingSystem.IsWindows() ? "dotnet.exe" : "dotnet"))
            {
                WorkingDirectory = root,
                UseShellExecute = false,
            };
            foreach (var argument in new[] { "restore", Path.Combine(root, entry), "--source", source, "--packages", packages, "-p:NuGetAudit=false" })
            {
                process.ArgumentList.Add(argument);
            }
            foreach (var (key, value) in contract.Properties)
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
