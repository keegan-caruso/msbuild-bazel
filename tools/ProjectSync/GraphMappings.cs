using System.Text.Json;
using Microsoft.Build.Construction;

namespace RulesMSBuild.ProjectSync;

// Graph execution retains targets. Mappings attest their input contract rather
// than replacing MSBuild target execution.
internal sealed class GraphMappings
{
    private readonly Mappings mappings;

    internal GraphMappings(string? path)
    {
        if (path is not null)
        {
            using var json = JsonDocument.Parse(File.ReadAllText(path));
            foreach (var section in json.RootElement.EnumerateObject())
            {
                if (section.Name is "projectDefaults")
                {
                    Validate(section.Value, defaults: true);
                }
                else if (section.Name is "projects")
                {
                    foreach (var project in section.Value.EnumerateObject())
                    {
                        Validate(project.Value, defaults: false);
                    }
                }
                else if (section.Name != "entryProperties")
                {
                    throw new InvalidDataException("Graph mappings do not support section: " + section.Name);
                }
            }
        }
        mappings = Mappings.Read(path);
        var owned = new[] { "NetCoreSdkRoot", "DOTNET_HOST_PATH", "PathMap", "UseSharedCompilation", "RestoreSources", "RestoreConfigFile", "RestorePackagesPath", "RestoreFallbackFolders", "RestoreAdditionalProjectSources", "RestoreAdditionalProjectFallbackFolders" };
        if (mappings.ProjectDefaults.Properties.Keys.Any(key => owned.Contains(key, StringComparer.OrdinalIgnoreCase)))
        {
            throw new InvalidDataException("Graph paths and Restore sources are controlled by declared inputs");
        }
    }

    private static void Validate(JsonElement binding, bool defaults)
    {
        foreach (var property in binding.EnumerateObject())
        {
            if (property.Name == "frameworkOverrides")
            {
                foreach (var framework in property.Value.EnumerateObject())
                {
                    Validate(framework.Value, defaults: false);
                }
                continue;
            }
            if (property.Name is not ("documents" or "inputItems" or "evaluationItems" or "evaluationReuseInputs" or "outputFiles" or "replayOmissions" or "referenceBoundary" or "implementationDependencies" or "compilerReference" or "compilerReferences" or "dependencyCopies" or "preparedRestore" or "restoreInputs" or "restoreOutputs" or "inputDirectories" or "temporaryDirectories") && !(defaults && property.Name == "properties"))
            {
                throw new InvalidDataException("Graph mapping requires explicit contract transfer for: " + property.Name);
            }
        }
    }

    internal Dictionary<string, Dictionary<string, string>> EntryProperties => mappings.EntryProperties;

    internal Dictionary<string, string> Properties => mappings.ProjectDefaults.Properties;

    internal ProjectBinding ForProject(string project, string framework = "")
    {
        var binding = mappings.ForProject(project);
        return binding.FrameworkOverrides.GetValueOrDefault(framework) ?? binding;
    }

    internal static IEnumerable<string> Inputs(ProjectRootElement document, string logical, ProjectBinding binding)
    {
        if (!binding.Documents.TryGetValue(logical, out var contract))
        {
            if (document.Targets.Count != 0 || document.UsingTasks.Count != 0)
            {
                throw new InvalidDataException("Graph custom targets/tasks require reviewed documents mappings: " + logical);
            }
            return [];
        }
        var digest = Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(document.FullPath)));
        if (contract.Sha256 != digest || !document.Targets.Select(target => target.Name).ToHashSet(StringComparer.Ordinal).SetEquals(contract.Targets) ||
            !document.UsingTasks.Select(task => task.TaskName).ToHashSet(StringComparer.Ordinal).SetEquals(contract.Tasks))
        {
            throw new InvalidDataException("Custom document contract changed: " + logical);
        }
        return contract.Inputs.Select(WorkspaceView.Safe);
    }
}
