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

internal sealed class ReferenceBinding
{
    public string[] Labels { get; set; } = [];
    public string OutputItemType { get; set; } = "";
    public string Targets { get; set; } = "";
    public string[] Roles { get; set; } = [];
    public string Role { get; set; } = "";
    public string Label { get; set; } = "";
}

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
    public Dictionary<string, PackageBinding> Packages { get; set; } = [];
    public string[] TargetFrameworks { get; set; } = [];
    public string Platform { get; set; } = "AnyCPU";
    public bool LinuxWorker
    {
        get; set;
    }
    public bool ProfileBuild
    {
        get; set;
    }
    public bool? UseAppHost
    {
        get; set;
    }
    public bool? TransitiveCompileReferences
    {
        get; set;
    }
    public Dictionary<string, string[]> PackageReferencePaths { get; set; } = [];
    public Dictionary<string, ReferenceBinding> References { get; set; } = [];
    public Dictionary<string, ReferenceBinding> ProjectReferences { get; set; } = [];
    public string OutputMode { get; set; } = "sdk";
    public string? PackageLock
    {
        get; set;
    }
    public string? ReferencePack
    {
        get; set;
    }
    public string? RuntimeHost
    {
        get; set;
    }
    public string[] Tools { get; set; } = [];
    public string[] Bindings { get; set; } = [];
    public string[] AssemblySelections { get; set; } = [];
    public string[] Items { get; set; } = [];
    public Dictionary<string, string> ItemPaths { get; set; } = [];
    public string[] AdapterImports { get; set; } = [];
    public string[] Directories { get; set; } = [];
    public Dictionary<string, string> GeneratedDirectories { get; set; } = [];
    public Dictionary<string, string> LayoutBindings { get; set; } = [];
    public Dictionary<string, DocumentBinding> Documents { get; set; } = [];
    public Dictionary<string, string[]> InputItems { get; set; } = [];
    public Dictionary<string, string[]> ExportTargets { get; set; } = [];
    public string[] EvaluationItems { get; set; } = [];
    public Dictionary<string, string> Properties { get; set; } = [];
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
    public string? SettingsOutput
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
    public ProjectBinding ProjectDefaults { get; set; } = new();
    public Dictionary<string, PackageBinding> Packages { get; set; } = [];
    public Dictionary<string, TestBinding> Tests { get; set; } = [];
    public Dictionary<string, ProjectBinding> Projects { get; set; } = [];

    internal static Mappings Read(string? path)
    {
        var mappings = path is null ? new Mappings() : JsonSerializer.Deserialize<Mappings>(MappingDefaults.Expand(File.ReadAllText(path)), new JsonSerializerOptions { PropertyNameCaseInsensitive = true, UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow }) ?? throw new InvalidDataException("Empty sync mappings");
        ValidatePackages(mappings.Packages);
        foreach (var project in mappings.Projects.Keys)
        {
            ProjectPath(project);
        }
        foreach (var (project, binding) in mappings.Projects.Append(new KeyValuePair<string, ProjectBinding>("projectDefaults", mappings.ProjectDefaults)).SelectMany(p => p.Value.FrameworkOverrides.Select(v => new KeyValuePair<string, ProjectBinding>(p.Key + " [" + v.Key + "]", v.Value)).Prepend(p)))
        {
            if (string.IsNullOrWhiteSpace(binding.Platform))
            {
                throw new InvalidDataException("Project platform must be explicit and nonempty: " + project);
            }
            Properties(binding.Properties);
            ValidatePackages(binding.Packages);
            foreach (var (type, metadata) in binding.InputItems)
            {
                System.Xml.XmlConvert.VerifyNCName(type);
                if (type.StartsWith("_Bazel", StringComparison.OrdinalIgnoreCase) || new[] { "Compile", "ProjectReference", "Reference", "Analyzer", "PackageReference", "PackageVersion", "FrameworkReference" }.Contains(type, StringComparer.OrdinalIgnoreCase))
                {
                    throw new InvalidDataException("Use dependency/source mappings for input item type: " + type);
                }
                foreach (var name in metadata)
                {
                    System.Xml.XmlConvert.VerifyNCName(name);
                }
            }
            foreach (var (source, destination) in binding.GeneratedDirectories)
            {
                WorkspaceView.Safe(source);
                WorkspaceView.Safe(destination);
            }
            foreach (var (target, outputs) in binding.ExportTargets)
            {
                System.Xml.XmlConvert.VerifyNCName(target);
                foreach (var output in outputs)
                {
                    WorkspaceView.Safe(output);
                }
            }
            foreach (var (package, paths) in binding.PackageReferencePaths)
            {
                if (package.Length == 0 || package.Any(c => !char.IsAsciiLetterOrDigit(c) && c is not '.' and not '-' and not '_') || paths.Length == 0)
                {
                    throw new InvalidDataException("Package reference paths require a package ID and explicit paths: " + project);
                }
                foreach (var assetPath in paths)
                {
                    WorkspaceView.Safe(assetPath);
                }
            }
            foreach (var (source, destination) in binding.ItemPaths)
            {
                WorkspaceView.Safe(source);
                WorkspaceView.Safe(destination);
            }
            if (binding.OutputMode is not "sdk" and not "reference" and not "implementation")
            {
                throw new InvalidDataException("Invalid output mode: " + project);
            }
            foreach (var label in binding.Tools.Concat(binding.AssemblySelections).Concat(binding.LayoutBindings.Keys).Concat(binding.Bindings).Concat(binding.Items).Concat(binding.AdapterImports).Concat(binding.ReferencePack is null ? [] : new[] { binding.ReferencePack }).Concat(binding.RuntimeHost is null ? [] : new[] { binding.RuntimeHost }).Concat(binding.PackageLock is null ? [] : new[] { binding.PackageLock }))
            {
                Label(label);
            }
            foreach (var (identity, reference) in binding.References.Concat(binding.ProjectReferences))
            {
                if (identity.Length == 0 || reference.Role is not "compile" and not "private" and not "analyzer" and not "tool" and not "output" and not "package" and not "framework" and not "items")
                {
                    throw new InvalidDataException("Invalid explicit reference role: " + identity);
                }
                if (reference.Roles.Any(role => role is not "build_deps" and not "analyzers") || reference.Roles.Length != 0 && reference.Role != "package")
                {
                    throw new InvalidDataException("Additional asset roles require a package reference binding");
                }
                if (reference.Role == "items")
                {
                    if (reference.Label.Length != 0 || reference.Labels.Length == 0 || reference.OutputItemType.Length == 0 || reference.Targets.Length == 0)
                    {
                        throw new InvalidDataException("Item project references require labels, outputItemType and targets: " + identity);
                    }
                    foreach (var itemLabel in reference.Labels)
                    {
                        Label(itemLabel);
                    }
                }
                else if (reference.Labels.Length != 0 || reference.OutputItemType.Length != 0 || reference.Targets.Length != 0)
                {
                    throw new InvalidDataException("Item output contracts require the items role: " + identity);
                }
                if (reference.Role is not "framework" and not "items")
                {
                    Label(reference.Label);
                }
            }
            if (binding.TargetFrameworks.Any(tfm => tfm.Length == 0 || tfm.Any(c => !char.IsAsciiLetterLower(c) && !char.IsAsciiDigit(c) && c is not '.' and not '-')) || binding.TargetFrameworks.Distinct(StringComparer.Ordinal).Count() != binding.TargetFrameworks.Length)
            {
                throw new InvalidDataException("Expected distinct lowercase target frameworks: " + project);
            }
        }
        foreach (var (project, test) in mappings.Tests)
        {
            ProjectPath(project);
            Properties(test.Properties);
            if (test.Settings is not null && test.SettingsOutput is not null)
            {
                throw new InvalidDataException("Declare either settings or settingsOutput: " + project);
            }
            if (test.SettingsOutput is not null)
            {
                WorkspaceView.Safe(test.SettingsOutput);
            }

            if (test.Protocol is not "vstest" and not "mtp" and not "executable")
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
            if (test.OutputType is not null and not "exe" and not "library")
            {
                throw new InvalidDataException("Invalid test output type or reserved evaluation property: " + project);
            }
        }
        return mappings;
    }

    private static void ProjectPath(string project)
    {
        if (Path.IsPathRooted(project) || project.Contains('\\') || project.Split('/').Any(p => p is "" or "." or "..") || !project.EndsWith(".csproj", StringComparison.Ordinal))
        {
            throw new InvalidDataException("Expected a workspace-relative csproj: " + project);
        }
    }

    private static void Properties(Dictionary<string, string> properties)
    {
        var keys = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var key in properties.Keys)
        {
            System.Xml.XmlConvert.VerifyNCName(key);
            if (!keys.Add(key) || new[] { "Platform", "Configuration", "TargetFramework", "TargetFrameworks", "OutputType", "UseAppHost", "ImportProjectExtensionProps", "ImportProjectExtensionTargets" }.Contains(key, StringComparer.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("Duplicate or reserved evaluation property: " + key);
            }
        }
    }

    internal ProjectBinding ForProject(string project) => Projects.GetValueOrDefault(project) ?? ProjectDefaults;

    internal Dictionary<string, string> ProjectProperties(string project, TestBinding? test, ProjectBinding? binding = null)
    {
        binding ??= ForProject(project);
        var properties = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) { ["Platform"] = binding.Platform };
        foreach (var (key, value) in binding.Properties)
        {
            properties.Add(key, value);
        }
        foreach (var (key, value) in test?.Properties ?? [])
        {
            if (properties.TryGetValue(key, out var previous) && previous != value)
            {
                throw new InvalidDataException("Conflicting project/test evaluation property: " + key);
            }
            properties[key] = value;
        }
        return properties;
    }

    private static void Label(string label)
    {
        if (!(label.StartsWith(':') || label.StartsWith("//", StringComparison.Ordinal) || label.StartsWith('@') && label.Contains("//", StringComparison.Ordinal)) || label.Length < 2 || label.Any(char.IsWhiteSpace))
        {
            throw new InvalidDataException("Expected an explicit Bazel label: " + label);
        }
    }

    private static void ValidatePackages(Dictionary<string, PackageBinding> packages)
    {
        var identities = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var (identity, binding) in packages)
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
    }

    internal Dictionary<string, List<string>> PackageAttributes(Project project, ProjectBinding projectBinding)
    {
        var attributes = new Dictionary<string, List<string>> { ["deps"] = [], ["build_deps"] = [], ["analyzers"] = [] };
        foreach (var package in project.GetItems("PackageReference"))
        {
            foreach (var metadata in package.Metadata)
            {
                if (metadata.Name is not "Version" and not "PrivateAssets" and not "IsImplicitlyDefined" and not "GeneratePathProperty" and not "IncludeAssets" and not "ExcludeAssets" and not "VersionOverride" and not "Publish" and not "AllowExplicitVersion")
                {
                    throw new InvalidDataException("PackageReference metadata requires explicit mapping: " + metadata.Name);
                }
            }
            foreach (var flag in new[] { "IsImplicitlyDefined", "GeneratePathProperty", "Publish", "AllowExplicitVersion" })
            {
                var value = package.GetMetadataValue(flag);
                if (value.Length != 0 && !bool.TryParse(value, out _))
                {
                    throw new InvalidDataException("Invalid PackageReference metadata: " + flag);
                }
            }
            foreach (var mask in new[] { "PrivateAssets", "IncludeAssets", "ExcludeAssets" })
            {
                var values = package.GetMetadataValue(mask).ToLowerInvariant().Split(';', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);
                if (values.Any(value => value is not "all" and not "none" and not "compile" and not "runtime" and not "native" and not "contentfiles" and not "analyzers" and not "build" and not "buildtransitive" and not "buildmultitargeting") || values.Length > 1 && values.Any(value => value is "all" or "none"))
                {
                    throw new InvalidDataException("Invalid PackageReference asset mask: " + mask);
                }
            }
            var version = package.GetMetadataValue("VersionOverride");
            if (version.Length != 0 && project.GetPropertyValue("CentralPackageVersionOverrideEnabled").Equals("false", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("Central package version overrides are disabled");
            }
            if (version.Length == 0)
            {
                version = package.GetMetadataValue("Version");
            }
            if (version.Length == 0 && project.GetPropertyValue("ManagePackageVersionsCentrally").Equals("true", StringComparison.OrdinalIgnoreCase))
            {
                version = project.GetItems("PackageVersion").SingleOrDefault(i => i.EvaluatedInclude.Equals(package.EvaluatedInclude, StringComparison.OrdinalIgnoreCase))?.GetMetadataValue("Version") ?? "";
            }
            var identity = package.EvaluatedInclude + "/" + version;
            var binding = projectBinding.Packages.FirstOrDefault(p => p.Key.Equals(identity, StringComparison.OrdinalIgnoreCase)).Value ?? Packages.FirstOrDefault(p => p.Key.Equals(identity, StringComparison.OrdinalIgnoreCase)).Value ?? throw new InvalidDataException("PackageReference requires an exact package mapping: " + identity);
            foreach (var role in binding.Roles)
            {
                attributes[role].Add(binding.Label);
            }
            attributes["analyzers"].AddRange(binding.Analyzers);
        }
        return attributes;
    }

    internal static Dictionary<string, string> PackagePrivacy(Project project, ProjectBinding binding) => project.GetItems("PackageReference").Concat(project.GetItems("Reference").Where(item => binding.References.TryGetValue(item.EvaluatedInclude, out var reference) && reference.Role == "package"))
        .Where(item => item.GetMetadataValue("PrivateAssets").Length != 0)
        .ToDictionary(item => item.EvaluatedInclude, item => item.GetMetadataValue("PrivateAssets").ToLowerInvariant(), StringComparer.OrdinalIgnoreCase);

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
        if (test.SettingsOutput is not null)
        {
            attributes["test_settings_output"] = test.SettingsOutput;
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
        return attributes;
    }
}
