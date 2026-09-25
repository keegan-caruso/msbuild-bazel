using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Build.Evaluation;

namespace RulesMSBuild.ProjectSync;

internal sealed class PackageBinding
{
    public string Label { get; set; } = "";
    public string[] Roles { get; set; } = [];
    public string[] Analyzers { get; set; } = [];
}

internal sealed class TestBinding
{
    public string Protocol { get; set; } = "";
    public string? Runner
    {
        get; set;
    }
    public string[] Adapters { get; set; } = [];
    public string? OutputType
    {
        get; set;
    }
    public string? Settings
    {
        get; set;
    }
    public string? WorkingDirectory
    {
        get; set;
    }
    public string[] OutputDirectories { get; set; } = [];
    public string? FilterArgument
    {
        get; set;
    }
    public Dictionary<string, string> DataPaths { get; set; } = [];
    public Dictionary<string, string> Environment { get; set; } = [];
    public Dictionary<string, string> Properties { get; set; } = [];
}

internal sealed class Mappings
{
    public Dictionary<string, PackageBinding> Packages { get; set; } = [];
    public Dictionary<string, TestBinding> Tests { get; set; } = [];

    internal static Mappings Read(string? path)
    {
        var mappings = path is null ? new Mappings() : JsonSerializer.Deserialize<Mappings>(File.ReadAllText(path), new JsonSerializerOptions { PropertyNameCaseInsensitive = true, UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow }) ?? throw new InvalidDataException("Empty sync mappings");
        var identities = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var (identity, binding) in mappings.Packages)
        {
            if (!identities.Add(identity) || identity.Split('/') is not [var id, var version] || id.Length == 0 || version.Length == 0 || binding.Roles.Length == 0 || binding.Roles.Any(r => r is not "deps" and not "build_deps" and not "analyzers"))
            {
                throw new InvalidDataException("Package mappings require unique ID/version keys and explicit deps/build_deps/analyzers roles: " + identity);
            }
            Label(binding.Label);
            foreach (var label in binding.Analyzers)
            {
                Label(label);
            }
        }
        foreach (var (project, test) in mappings.Tests)
        {
            if (Path.IsPathRooted(project) || project.Split('/').Any(p => p is "" or "." or "..") || !project.EndsWith(".csproj", StringComparison.Ordinal) || test.Protocol is not "vstest" and not "mtp" and not "executable")
            {
                throw new InvalidDataException("Test mappings require a workspace-relative csproj and explicit protocol: " + project);
            }
            if (test.Protocol == "vstest")
            {
                Label(test.Runner ?? "");
                foreach (var adapter in test.Adapters)
                {
                    Label(adapter);
                }
            }
            else if (test.Runner is not null || test.Adapters.Length != 0)
            {
                throw new InvalidDataException("Runner and adapters are VSTest-only: " + project);
            }
            if (test.OutputType is not null and not "exe" and not "library" || test.Properties.Keys.Any(k => new[] { "Platform", "Configuration", "TargetFramework", "TargetFrameworks", "OutputType", "ImportProjectExtensionProps", "ImportProjectExtensionTargets" }.Contains(k, StringComparer.OrdinalIgnoreCase)))
            {
                throw new InvalidDataException("Invalid test output type or reserved evaluation property: " + project);
            }
        }
        return mappings;
    }

    private static void Label(string label)
    {
        if (!(label.StartsWith(':') || label.StartsWith("//", StringComparison.Ordinal) || label.StartsWith('@') && label.Contains("//", StringComparison.Ordinal)) || label.Length < 2 || label.Any(char.IsWhiteSpace))
        {
            throw new InvalidDataException("Expected an explicit Bazel label: " + label);
        }
    }

    internal Dictionary<string, List<string>> PackageAttributes(Project project)
    {
        var attributes = new Dictionary<string, List<string>> { ["deps"] = [], ["build_deps"] = [], ["analyzers"] = [] };
        foreach (var package in project.GetItems("PackageReference"))
        {
            foreach (var metadata in package.DirectMetadata)
            {
                if (metadata.Name != "Version")
                {
                    throw new InvalidDataException("PackageReference metadata requires explicit mapping: " + metadata.Name);
                }
            }
            var version = package.GetMetadataValue("Version");
            if (version.Length == 0 && project.GetPropertyValue("ManagePackageVersionsCentrally").Equals("true", StringComparison.OrdinalIgnoreCase))
            {
                version = project.GetItems("PackageVersion").SingleOrDefault(i => i.EvaluatedInclude.Equals(package.EvaluatedInclude, StringComparison.OrdinalIgnoreCase))?.GetMetadataValue("Version") ?? "";
            }
            var identity = package.EvaluatedInclude + "/" + version;
            var binding = Packages.FirstOrDefault(p => p.Key.Equals(identity, StringComparison.OrdinalIgnoreCase)).Value ?? throw new InvalidDataException("PackageReference requires an exact package mapping: " + identity);
            foreach (var role in binding.Roles)
            {
                attributes[role].Add(binding.Label);
            }
            attributes["analyzers"].AddRange(binding.Analyzers);
        }
        return attributes;
    }

    internal static Dictionary<string, object> TestAttributes(TestBinding test, string outputType)
    {
        var attributes = new Dictionary<string, object> { ["test_protocol"] = test.Protocol, ["test_output_type"] = test.OutputType ?? (outputType == "Exe" ? "exe" : "library") };
        if (test.Protocol != "vstest" && attributes["test_output_type"].ToString() != "exe")
        {
            throw new InvalidDataException("Executable/MTP test mappings require an executable project or explicit outputType=exe");
        }
        if (test.Runner is not null)
        {
            attributes["test_runner"] = test.Runner;
            attributes["test_adapters"] = test.Adapters;
        }
        if (test.Settings is not null)
        {
            attributes["test_settings"] = test.Settings;
        }
        if (test.WorkingDirectory is not null)
        {
            attributes["test_working_directory"] = test.WorkingDirectory;
        }
        if (test.FilterArgument is not null)
        {
            attributes["test_filter_argument"] = test.FilterArgument;
        }
        attributes["test_output_dirs"] = test.OutputDirectories;
        attributes["data_paths"] = test.DataPaths;
        attributes["env"] = test.Environment;
        attributes["msbuild_properties"] = new Dictionary<string, string>(test.Properties) { ["Platform"] = "AnyCPU" };
        return attributes;
    }
}
