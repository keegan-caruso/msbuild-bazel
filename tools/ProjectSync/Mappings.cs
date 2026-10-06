using System.Text.Json;
using System.Text.Json.Serialization;

namespace RulesMSBuild.ProjectSync;

internal sealed class DocumentBinding
{
    public string Sha256 { get; set; } = "";
    public string[] Targets { get; set; } = [];
    public string[] Tasks { get; set; } = [];
    public string[] Inputs { get; set; } = [];
}

internal sealed class ProjectBinding
{
    public Dictionary<string, ProjectBinding> FrameworkOverrides { get; set; } = [];
    public bool PreparedRestore { get; set; } = false;
    public string[] InputDirectories { get; set; } = [];
    public string[] TemporaryDirectories { get; set; } = [];
    public string[] RestoreInputs { get; set; } = [];
    public string[] RestoreOutputs { get; set; } = [];
    public string[] OutputFiles { get; set; } = [];
    public string[] ReplayOmissions { get; set; } = [];
    public bool? ReferenceBoundary { get; set; } = null;
    public string[] ImplementationDependencies { get; set; } = [];
    public string? CompilerReference { get; set; } = null;
    public Dictionary<string, string> CompilerReferences { get; set; } = [];
    public Dictionary<string, string> DependencyCopies { get; set; } = [];
    public Dictionary<string, DocumentBinding> Documents { get; set; } = [];
    public Dictionary<string, string[]> InputItems { get; set; } = [];
    public string[] EvaluationReuseInputs { get; set; } = [];
    public string[] EvaluationItems { get; set; } = [];
    public Dictionary<string, string> Properties { get; set; } = [];
}

internal sealed class Mappings
{
    public ProjectBinding ProjectDefaults { get; set; } = new();
    public Dictionary<string, Dictionary<string, string>> EntryProperties { get; set; } = [];
    public Dictionary<string, ProjectBinding> Projects { get; set; } = [];

    internal static Mappings Read(string? path)
    {
        var mappings = path is null ? new Mappings() : JsonSerializer.Deserialize<Mappings>(MappingDefaults.Expand(File.ReadAllText(path)), new JsonSerializerOptions { PropertyNameCaseInsensitive = true, UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow }) ?? throw new InvalidDataException("Empty sync mappings");
        foreach (var project in mappings.Projects.Keys)
        {
            WorkspaceView.Safe(project);
            if (!project.EndsWith(".csproj", StringComparison.Ordinal) && !project.EndsWith(".proj", StringComparison.Ordinal) && !project.EndsWith(".ilproj", StringComparison.Ordinal))
            {
                throw new InvalidDataException("Expected a workspace-relative .csproj, .proj or .ilproj: " + project);
            }
        }
        foreach (var binding in mappings.Projects.Values.Append(mappings.ProjectDefaults).SelectMany(binding => binding.FrameworkOverrides.Values.Prepend(binding)))
        {
            foreach (var (type, metadata) in binding.InputItems)
            {
                System.Xml.XmlConvert.VerifyNCName(type);
                if (type.StartsWith("_Bazel", StringComparison.OrdinalIgnoreCase) || new[] { "Compile", "ProjectReference", "Reference", "Analyzer", "PackageReference", "PackageVersion", "FrameworkReference" }.Contains(type, StringComparer.OrdinalIgnoreCase))
                {
                    throw new InvalidDataException("Use dependency/source contracts for input item type: " + type);
                }
                foreach (var name in metadata)
                {
                    System.Xml.XmlConvert.VerifyNCName(name);
                }
            }
            foreach (var input in binding.RestoreInputs.Concat(binding.RestoreOutputs).Concat(binding.InputDirectories))
            {
                WorkspaceView.Safe(input);
            }
            if ((binding.RestoreInputs.Length != 0 || binding.RestoreOutputs.Length != 0) && !binding.PreparedRestore)
            {
                throw new InvalidDataException("restoreInputs and restoreOutputs require preparedRestore");
            }
        }
        return mappings;
    }

    internal ProjectBinding ForProject(string project) => Projects.GetValueOrDefault(project) ?? ProjectDefaults;
}
