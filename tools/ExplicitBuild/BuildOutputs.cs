using System.Text.Json;
using static Program;

internal static class BuildOutputs
{
    internal static void Publish(Request r, string state)
    {
        var diagnostics = ReadPath(r.Diagnostics);
        Directory.CreateDirectory(diagnostics);
        if (r.GenerateTargets is { Length: > 0 })
        {
            GeneratedFiles.Publish(r, state);
            return;
        }
        if (r.RestoreOnly)
        {
            Directory.CreateDirectory(ReadPath(r.Runtime));
            Copy(Path.Combine(state, "restore.json"), ReadPath(r.Reference));
            return;
        }
        if (r.RestoreProjectOutput is not null)
        {
            Copy(Path.Combine(state, "project-restore.json"), ReadPath(r.RestoreProjectOutput));
        }

        if (r.TargetOutput is not null)
        {
            Copy(Path.Combine(state, "targets.json"), ReadPath(r.TargetOutput));
        }

        var output = Path.Combine(state, "out");
        var runtime = ReadPath(r.Runtime);
        Directory.CreateDirectory(runtime);
        var referenceNames = r.References.Select(Path.GetFileName).ToHashSet(StringComparer.Ordinal);
        if (referenceNames.Contains(r.Assembly + ".dll"))
        {
            throw new InvalidDataException("Dependency assembly name conflicts with this project");
        }

        var packageFiles = RuntimePackages.ReadFiles(output);
        foreach (var file in r.OutputMode == "reference" ? [] : Directory.GetFiles(output, "*", SearchOption.AllDirectories))
        {
            if (!referenceNames.Contains(Path.GetRelativePath(output, file)) && !packageFiles.ContainsKey(Path.GetRelativePath(output, file)))
            {
                Copy(file, Path.Combine(runtime, Path.GetRelativePath(output, file)));
            }
        }

        Copy(r.OutputMode == "sdk" ? Path.Combine(state, "obj", "ref", r.Assembly + ".dll") : Path.Combine(output, r.Assembly + ".dll"), ReadPath(r.Reference));
        if (r.IdentityOutput is not null)
        {
            AssemblyContracts.Export(Path.Combine(output, r.Assembly + ".dll"), ReadPath(r.IdentityOutput));
        }

        if (File.Exists(Path.Combine(state, "compile-profile.json")))
        {
            File.Copy(Path.Combine(state, "compile-profile.json"), Path.Combine(diagnostics, "compile-profile.json"), true);
        }

        File.WriteAllText(Path.Combine(diagnostics, "report.json"), JsonSerializer.Serialize(new
        {
            accepted = true,
            discovery = false,
            project = r.Project.Path
        }, Json));
    }
}
