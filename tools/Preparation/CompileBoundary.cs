using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;

namespace RulesMSBuild.Preparation;

internal static class CompileBoundary
{
    private static readonly HashSet<string> Properties = new(("TargetFramework OutputType AssemblyName RootNamespace EnableDefaultCompileItems Nullable ImplicitUsings LangVersion Version OfficialBuildId BuildStamp Value Description Authors Copyright AssemblyVersion TargetFrameworks PackageTags PackageIcon PackageProjectUrl PackageLicenseExpression IsAotCompatible NoWarn PolySharpIncludeRuntimeSupportedAttributes PolySharpExcludeGeneratedTypes PackageReadmeFile DisableImplicitFrameworkReferences DefineConstants VersionPrefix TreatWarningsAsErrors SignAssembly AssemblyOriginatorKeyFile CheckEolTargetFramework GenerateDocumentationFile PublishRepositoryUrl EmbedUntrackedSources IncludeSymbols SymbolPackageFormat").Split(' '), StringComparer.Ordinal);
    private static readonly Dictionary<string, string> Switches = new() { ["UseAppHost"] = "false", ["UseSharedCompilation"] = "false", ["EnableNETAnalyzers"] = "false", ["Deterministic"] = "true", ["DisableTransitiveProjectReferences"] = "true", ["DeterministicSourcePaths"] = "false" };
    private static readonly HashSet<string> Items = new(["Compile", "None", "EmbeddedResource", "Content", "AdditionalFiles", "BazelExtraInput", "ProjectReference", "Reference", "PackageReference", "Using", "RuntimeHostConfigurationOption"], StringComparer.Ordinal);
    public static void Validate(string workspace, JsonNode graph, Packages packages)
    {
        var checkedPaths = new HashSet<string>(StringComparer.Ordinal);
        var depended = graph.Array("nodes").SelectMany(n => n!.Array("dependencies")).Select(n => n!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
        foreach (var node in graph.Array("nodes").Select(n => n ?? throw new InvalidDataException("null graph node")))
        {
            if (packages.Plan(Host.Relative(node!.String("project")), Host.Relative(GraphPreparation.Execution(node).String("assetsFile")), node.String("targetFramework")).Count != 0) throw new InvalidDataException("compile boundary requires package-free SDK projects");
            if (node["globalProperties"]!.AsObject().Any(p => p.Key is not ("configuration" or "targetframework")) || node["globalProperties"]!.String("configuration") != "Release") throw new InvalidDataException("compile boundary requires the qualified Release configuration");
            if (depended.Contains(node.String("id")) && node.String("outputType") != "Library") throw new InvalidDataException("executable project references require full bundles");
            if (node.String("targetFramework") != "net10.0") throw new InvalidDataException("compile boundary requires net10.0");
            foreach (var item in node.Array("inputs"))
            {
                var path = item!.String("path"); var kind = item.String("kind");
                if (kind is "package" or "content" or "resource" or "additional" or "extra" or "signing" || path.StartsWith("packages/", StringComparison.Ordinal)) throw new InvalidDataException("compile boundary requires package-free SDK projects");
                if (kind == "analyzer" && !path.StartsWith("dotnet/packs/Microsoft.NETCore.App.Ref/", StringComparison.Ordinal)) throw new InvalidDataException("implementation-consuming analyzer requires full dependency bundle");
                if (kind is not ("project" or "import") || !path.StartsWith("workspace/", StringComparison.Ordinal)) continue;
                var local = Path.Combine(workspace, Host.Relative(path));
                if (!checkedPaths.Add(local)) continue;
                var tree = CheckXml(local);
                foreach (var element in tree.Descendants())
                {
                    var tag = element.Name.LocalName;
                    if (tag is "PackageReference" or "Reference" or "Content" or "EmbeddedResource" or "AdditionalFiles" or "BazelExtraInput") throw new InvalidDataException("unqualified compile boundary item: " + tag);
                    if (tag == "None" && element.Attributes().Any(a => a.Name.LocalName is not ("Include" or "Remove" or "Update" or "Condition"))) throw new InvalidDataException("unqualified runtime content metadata");
                }
            }
        }
    }
    private static void Expression(string value)
    {
        value = Regex.Replace(value, "%([0-9a-f]{2})", m => ((char)Convert.ToInt32(m.Groups[1].Value, 16)).ToString(), RegexOptions.IgnoreCase);
        foreach (var pure in new[] { "$(VersionPrefix.Substring(0,3))", "$(MSBuildProjectName.EndsWith('Tests'))", "$([MSBuild]::IsTargetFrameworkCompatible('$(TargetFramework)', 'net7.0'))" }) value = value.Replace(pure, "", StringComparison.Ordinal);
        value = Regex.Replace(value, @"\$\([A-Za-z_][A-Za-z_0-9]*\)", "");
        if (value.Contains("$(", StringComparison.Ordinal) || value.Contains("@(", StringComparison.Ordinal) || value.Contains("%(", StringComparison.Ordinal)) throw new InvalidDataException("unsupported discovery XML: property functions, item transforms and metadata expressions are not qualified");
    }
    private static XDocument CheckXml(string path)
    {
        using var reader = XmlReader.Create(path, new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null });
        var tree = XDocument.Load(reader); var generated = path.EndsWith(".nuget.g.props", StringComparison.Ordinal) || path.EndsWith(".nuget.g.targets", StringComparison.Ordinal);
        foreach (var element in tree.Root!.DescendantsAndSelf())
        {
            var name = element.Name.LocalName; var parent = element.Parent?.Name.LocalName;
            var valid = parent switch
            {
                null => name == "Project" && element.Attributes().Where(a => !a.IsNamespaceDeclaration).All(a => a.Name.LocalName is "Sdk" or "ToolsVersion") && ((string?)element.Attribute("Sdk") ?? "Microsoft.NET.Sdk") == "Microsoft.NET.Sdk" && (((string?)element.Attribute("ToolsVersion") ?? "Current") == "Current" || generated && (string?)element.Attribute("ToolsVersion") == "14.0"),
                "Project" => name is "PropertyGroup" or "ItemGroup" or "Import" or "ImportGroup" or "Choose",
                "Choose" => name is "When" or "Otherwise",
                "When" or "Otherwise" or "ImportGroup" => name is "PropertyGroup" or "ItemGroup" or "Import" or "Choose",
                "PropertyGroup" => Properties.Contains(name) || Switches.ContainsKey(name) || generated && name is "RestoreSuccess" or "RestoreTool" or "ProjectAssetsFile" or "NuGetPackageRoot" or "NuGetPackageFolders" or "NuGetProjectStyle" or "NuGetToolVersion" or "PkgMicrosoft_NET_ILLink_Tasks" or "Pkgxunit_analyzers",
                "ItemGroup" => Items.Contains(name) || generated && name == "SourceRoot",
                "EmbeddedResource" => name == "LogicalName",
                _ => false
            };
            if (!valid) throw new InvalidDataException("unsupported discovery XML: " + name);
            var attributes = new HashSet<string>(["Condition", "Label"], StringComparer.Ordinal);
            if (name == "Project") attributes.UnionWith(["Sdk", "ToolsVersion"]);
            if (name == "Import") attributes.Add("Project");
            if (parent == "ItemGroup") attributes.UnionWith(["Include", "Exclude", "Remove", "Update"]);
            if (name == "None") attributes.UnionWith(["Pack", "Visible", "PackagePath"]);
            if (name == "PackageReference") attributes.UnionWith(["Version", "PrivateAssets"]);
            if (name == "RuntimeHostConfigurationOption")
            {
                var expected = new Dictionary<string, string> { ["Condition"] = "'$(PublishTrimmed)' == 'true'", ["Include"] = "Serilog.Capturing.IsStructureValueSupported", ["Value"] = "false", ["Trim"] = "true" };
                if (element.Attributes().Count() != expected.Count || element.Attributes().Any(a => !expected.TryGetValue(a.Name.LocalName, out var value) || a.Value != value)) throw new InvalidDataException("unqualified runtime configuration option");
                attributes.UnionWith(["Value", "Trim"]);
            }
            foreach (var attribute in element.Attributes().Where(a => !a.IsNamespaceDeclaration))
            {
                if (attribute.Name.NamespaceName.Length != 0 || !attributes.Contains(attribute.Name.LocalName)) throw new InvalidDataException("unsupported discovery XML: attributes on " + name);
                Expression(attribute.Value);
            }
            var text = string.Concat(element.Nodes().OfType<XText>().Select(t => t.Value));
            if (Switches.TryGetValue(name, out var required) && text.Trim() != required) throw new InvalidDataException("unqualified SDK switch value: " + name);
            Expression(text);
        }
        return tree;
    }
}
