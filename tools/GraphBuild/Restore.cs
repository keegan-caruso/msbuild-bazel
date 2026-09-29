using System.Diagnostics;

namespace RulesMSBuild.GraphBuild;

internal static class Restore
{
    internal static GraphContract Run(GraphContract contract, string root, string sdkRoot)
    {
        var packages = Path.Combine(root, ".nuget");
        var source = Path.Combine(root, ".package-source");
        Directory.CreateDirectory(source);
        var process = new ProcessStartInfo(Path.Combine(sdkRoot, OperatingSystem.IsWindows() ? "dotnet.exe" : "dotnet"))
        {
            WorkingDirectory = root,
            UseShellExecute = false,
        };
        foreach (var argument in new[] { "restore", Path.Combine(root, contract.Entry), "--source", source, "--packages", packages, "-p:NuGetAudit=false" })
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
        var projects = new Dictionary<string, ProjectContract>(StringComparer.Ordinal);
        foreach (var (relative, project) in contract.Projects)
        {
            var directory = Path.Combine(root, Path.GetDirectoryName(relative)!, "obj");
            var generated = new[] { "project.assets.json", Path.GetFileName(relative) + ".nuget.g.props", Path.GetFileName(relative) + ".nuget.g.targets" }
                .Select(name => Path.Combine(directory, name));
            if (generated.Any(path => !File.Exists(path)))
            {
                throw new InvalidDataException("Automatic graph Restore currently requires default obj paths: " + relative);
            }
            projects.Add(relative, project with
            {
                Inputs = project.Inputs.Concat(generated.Select(path => Path.GetRelativePath(root, path))).Distinct().ToArray()
            });
        }
        var packageFiles = Directory.Exists(packages) ? Directory.GetFiles(packages, "*", SearchOption.AllDirectories)
            .Select(path => Path.GetRelativePath(root, path)) : [];
        return contract with
        {
            Projects = projects,
            SharedInputs = contract.SharedInputs.Concat(packageFiles).ToArray()
        };
    }
}
