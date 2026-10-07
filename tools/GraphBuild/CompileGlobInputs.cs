using Microsoft.Build.Execution;

namespace RulesMSBuild.GraphBuild;

// Expand only the staged action workspace, after prepared Restore key verification.
// The serialized pattern contract stays stable when source membership changes.
internal static class CompileGlobInputs
{
    internal static GraphContract Expand(GraphContract contract, ContractFiles files)
    {
        var patterns = contract.Projects.Values.SelectMany(project => (project.CompileGlobs ?? [])
            .Concat((project.Configurations ?? []).SelectMany(configuration => configuration.CompileGlobs ?? [])))
            .Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
        if (patterns.Length == 0 && contract.EvaluationReuseGlobs is null)
        {
            return contract;
        }
        if (contract.Version != 11)
        {
            throw new InvalidDataException("Compile globs require graph contract version 11");
        }
        var reserved = contract.SharedInputs.Concat((contract.DefinitionDigests ?? []).Keys)
            .Concat(contract.Restore?.Inputs ?? []).Concat(contract.Restore?.Outputs ?? []);
        var outputs = contract.Projects.Values.SelectMany(project => (project.OutputFiles ?? [])
            .Concat((project.Configurations ?? []).SelectMany(configuration => configuration.OutputFiles ?? [])));
        var directories = contract.Projects.Values.SelectMany(project => project.OutputDirectories
            .Concat((project.Configurations ?? []).SelectMany(configuration => configuration.OutputDirectories)))
            .Concat(contract.TemporaryDirectories ?? []);
        var members = new Dictionary<string, string[]>(StringComparer.Ordinal);
        foreach (var pattern in patterns)
        {
            if (reserved.Concat(outputs).Any(path => GraphSourcePattern.Matches(pattern, path)) ||
                directories.Any(path => GraphSourcePattern.OverlapsDirectory(pattern, path)))
            {
                throw new InvalidDataException("Compile glob overlaps definitions, Restore or owned outputs: " + pattern);
            }
            members.Add(pattern, Members(pattern, files));
        }
        string[] Inputs(string[] explicitInputs, string[]? globs) => explicitInputs.Concat((globs ?? [])
            .SelectMany(pattern => members[pattern])).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
        var projects = contract.Projects.ToDictionary(pair => pair.Key, pair => pair.Value with
        {
            Inputs = Inputs(pair.Value.Inputs, pair.Value.CompileGlobs),
            Configurations = pair.Value.Configurations?.Select(configuration => configuration with
            {
                Inputs = Inputs(configuration.Inputs, configuration.CompileGlobs)
            }).ToArray()
        }, StringComparer.Ordinal);
        var reuse = contract.EvaluationReuseGlobs;
        if (reuse is not null && (contract.EvaluationReuseInputs is null || contract.Restore is null ||
            reuse.Distinct(StringComparer.Ordinal).Count() != reuse.Length || reuse.Any(pattern => !members.ContainsKey(pattern))))
        {
            throw new InvalidDataException("Evaluation reuse globs must be distinct reviewed Compile patterns with prepared Restore");
        }
        // Resolve new members now to reject links before retained state or hashing.
        files.ResolveInputs(members.Values.SelectMany(paths => paths));
        return contract with
        {
            Projects = projects,
            EvaluationReuseInputs = contract.EvaluationReuseInputs is null ? null : Inputs(contract.EvaluationReuseInputs, reuse)
        };
    }

    internal static void VerifyUnchanged(GraphContract contract, ContractFiles files)
    {
        var projects = contract.Projects.Values;
        var patterns = projects.SelectMany(project => (project.CompileGlobs ?? [])
            .Concat((project.Configurations ?? []).SelectMany(configuration => configuration.CompileGlobs ?? []))).Distinct(StringComparer.Ordinal).ToArray();
        if (patterns.Length == 0)
        {
            return;
        }
        var inputs = projects.SelectMany(project => project.Inputs.Concat((project.Configurations ?? []).SelectMany(configuration => configuration.Inputs)))
            .ToHashSet(StringComparer.Ordinal);
        foreach (var pattern in patterns)
        {
            if (!Members(pattern, files).ToHashSet(StringComparer.Ordinal).SetEquals(inputs.Where(path => GraphSourcePattern.Matches(pattern, path))))
            {
                throw new InvalidDataException("Build modified Compile glob membership: " + pattern);
            }
        }
    }

    private static string[] Members(string pattern, ContractFiles files)
    {
        var directory = GraphSourcePattern.Directory(pattern);
        if (directory.Length != 0)
        {
            files.Resolve(directory);
        }
        return GraphSourcePattern.Members(files.Root, pattern);
    }

    internal static void Validate(ProjectInstance instance, ProjectContract contract, ContractFiles files)
    {
        foreach (var pattern in contract.CompileGlobs ?? [])
        {
            string Relative(string path) => Path.GetRelativePath(files.Root, Path.GetFullPath(path.Replace('\\', '/'), Path.GetDirectoryName(instance.FullPath)!)).Replace('\\', '/');
            var actual = instance.GetItems("Compile").Select(item => Relative(item.EvaluatedInclude))
                .Where(path => GraphSourcePattern.Matches(pattern, path)).ToHashSet(StringComparer.Ordinal);
            var expected = contract.Inputs.Where(path => GraphSourcePattern.Matches(pattern, path)).ToHashSet(StringComparer.Ordinal);
            var other = new[] { "EmbeddedResource", "Content", "None", "AdditionalFiles", "Analyzer", "EditorConfigFiles", "GlobalAnalyzerConfigFiles", "RazorGenerate" }
                .SelectMany(instance.GetItems).Select(item => Relative(item.EvaluatedInclude));
            if (!actual.SetEquals(expected) || other.Any(path => GraphSourcePattern.Matches(pattern, path)))
            {
                throw new InvalidDataException("Compile glob no longer selects only Compile items; rerun sync: " + pattern);
            }
        }
    }
}
