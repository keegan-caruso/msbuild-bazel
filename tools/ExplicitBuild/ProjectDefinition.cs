using System.Xml;

using System.Xml.Linq;
using static Program;

internal static class ProjectDefinition
{
    internal static void Write(Request r, string path, string references, Func<string, string> compilerPath, string[]? analyzerRoots)
    {
        var xml = XDocument.Load(path);
        var root = xml.Root!;
        if (root.Name != "Project" || root.Elements("Sdk").Any() || root.Attribute("Sdk") is not { } sdk || sdk.Value.Contains(';'))
        {
            throw new InvalidDataException("Initial explicit rules require one root Project Sdk attribute");
        }

        var sdkName = sdk.Value;
        sdk.Remove();
        root.AddFirst(new XElement("Import", new XAttribute("Project", "Sdk.props"), new XAttribute("Sdk", sdkName)));
        root.Add(new XElement("Import", new XAttribute("Project", "Sdk.targets"), new XAttribute("Sdk", sdkName)));
        foreach (var adapter in r.AdapterImports ?? [])
        {
            root.Add(new XElement("Import", new XAttribute("Project", Escape(compilerPath(Path.Combine(path[..^Safe(r.Project.Path).Length], Safe(adapter.Path)))))));
        }

        ReferencePackages.Inject(r, root);
        ReferenceProjects.Inject(r, root);
        root.Add(new XElement("ItemGroup", (r.FrameworkAssemblies ?? []).Select(name => new XElement("Reference", new XAttribute("Update", Escape(name)), new XElement("_BazelFrameworkAssembly", "true")))));
        // Preserve the original evaluated declarations before replacing them with
        // Bazel inputs. MSBuild copies condition-selected items and their metadata; validation
        // consumes these snapshots in the first evaluation already needed to build.
        var declarations = new XElement("ItemGroup");
        foreach (var type in new[] { "Compile", "ProjectReference", "PackageReference", "PackageVersion", "Reference", "Analyzer", "FrameworkReference" })
        {
            declarations.Add(new XElement("_BazelOriginal" + type, new XAttribute("Remove", "@(_BazelOriginal" + type + ")")));
            declarations.Add(new XElement("_BazelOriginal" + type, new XAttribute("Include", "@(" + type + ")")));
        }
        root.Add(declarations);
        var items = new XElement("ItemGroup");
        foreach (var type in r.Items.Select(i => i.Type).Concat(["Compile", "ProjectReference", "Reference", "PackageReference"]).Distinct(StringComparer.OrdinalIgnoreCase))
        {
            XmlConvert.VerifyNCName(type);
            if (type.StartsWith("_BazelOriginal", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("Reserved validation item type: " + type);
            }

            if (type.Equals("FrameworkReference", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("Use dependency attributes for " + type);
            }

            items.Add(new XElement(type, new XAttribute("Remove", "@(" + type + ")")));
        }
        var workspace = path[..^Safe(r.Project.Path).Length];
        foreach (var source in r.Sources)
        {
            items.Add(new XElement("Compile", new XAttribute("Include", Escape(compilerPath(Path.Combine(workspace, Safe(source.Path)))))));
        }
        // NuGet contentFiles are declared by the locked archive and retain their
        // evaluated metadata; replacing project sources must not discard them.
        items.Add(new XElement("Compile", new XAttribute("Include", "@(_BazelOriginalCompile->WithMetadataValue('NuGetItemType', 'Compile'))")));

        var sourcePaths = r.Sources.Select(source => source.Path).ToHashSet(StringComparer.Ordinal);
        foreach (var item in r.Items)
        {
            if (new[] { "ProjectReference", "Reference", "Analyzer", "PackageReference", "FrameworkReference" }.Contains(item.Type, StringComparer.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("Dependency items require typed dependency attributes");
            }

            var itemPath = Path.Combine(workspace, Safe(item.File.Path));
            var sourceMetadata = item.Type == "Compile" && sourcePaths.Contains(item.File.Path);
            var include = sourceMetadata || item.Type is "AdditionalFiles" or "GlobalAnalyzerConfigFiles" or "EditorConfigFiles"
                ? compilerPath(itemPath) : Path.GetRelativePath(Path.GetDirectoryName(path)!, itemPath);
            var element = new XElement(item.Type, new XAttribute(sourceMetadata ? "Update" : "Include", Escape(include)));
            foreach (var (name, value) in item.Metadata)
            {
                XmlConvert.VerifyNCName(name);
                if (name.Equals("FullPath", StringComparison.OrdinalIgnoreCase) || value.Contains("$(", StringComparison.Ordinal) || value.Contains("@(", StringComparison.Ordinal) || Path.IsPathRooted(value))
                {
                    throw new InvalidDataException("Unsafe item metadata: " + name);
                }

                element.Add(new XElement(name, Escape(value)));
            }
            items.Add(element);
        }
        ProjectOutputs.Inject(r, items, workspace, compilerPath);
        items.Add(new XElement("Reference", new XAttribute("Include", "@(_BazelOriginalReference)")));
        foreach (var reference in Directory.GetFiles(references).Concat(r.FrameworkInputs is null ? [] : Directory.GetFiles(Path.Combine(Path.GetDirectoryName(references)!, ".framework"))))
        {
            items.Add(new XElement("Reference", new XAttribute("Include", Path.GetFileNameWithoutExtension(reference)), new XElement("HintPath", Escape(compilerPath(reference))), new XElement("Private", Path.GetDirectoryName(reference) == references ? "true" : "false")));
        }
        // Keep the original NuGet metadata, then pin the supplied closed package set.
        // Only compile-visible inherited packages become new references; private
        // producer packages may remain declared files without becoming consumer inputs.
        foreach (var package in r.Packages.Where(p => r.DeclaredPackages.Contains(p.Id, StringComparer.OrdinalIgnoreCase) && r.CompilePackages.Contains(p.Id, StringComparer.OrdinalIgnoreCase)))
        {
            items.Add(new XElement("PackageReference", new XAttribute("Include", package.Id)));
        }

        items.Add(new XElement("PackageReference", new XAttribute("Remove", "@(_BazelOriginalPackageReference)")));
        items.Add(new XElement("PackageReference", new XAttribute("Include", "@(_BazelOriginalPackageReference)")));
        foreach (var package in r.Packages)
        {
            var excluded = new List<string>();
            if (!r.CompilePackages.Contains(package.Id, StringComparer.OrdinalIgnoreCase))
            {
                excluded.AddRange(["compile", "runtime", "native", "contentFiles"]);
            }

            if (!r.BuildPackages.Contains(package.Id, StringComparer.OrdinalIgnoreCase))
            {
                excluded.AddRange(["build", "buildTransitive", "buildMultitargeting"]);
            }

            if (!r.AnalyzerPackages.Contains(package.Id, StringComparer.OrdinalIgnoreCase))
            {
                excluded.Add("analyzers");
            }

            var central = "'$(ManagePackageVersionsCentrally)' == 'true' and '%(PackageReference.IsImplicitlyDefined)' != 'true'";
            items.Add(new XElement("PackageReference", new XAttribute("Update", package.Id),
                new XElement("Version", new XAttribute("Condition", central), ""),
                new XElement("Version", new XAttribute("Condition", "!(" + central + ")"), "[" + package.Version + "]"),
                new XElement("ExcludeAssets", "%(PackageReference.ExcludeAssets);" + string.Join(';', excluded))));
            items.Add(new XElement("PackageVersion", new XAttribute("Remove", package.Id)));
            items.Add(new XElement("PackageVersion", new XAttribute("Include", package.Id), new XAttribute("Version", "[" + package.Version + "]"),
                new XAttribute("Condition", "'$(ManagePackageVersionsCentrally)' == 'true' and '@(PackageReference->WithMetadataValue('Identity', '" + package.Id + "'))' != '' and '@(PackageReference->WithMetadataValue('IsImplicitlyDefined', 'true')->WithMetadataValue('Identity', '" + package.Id + "'))' == ''")));
        }
        foreach (var framework in r.FrameworkReferences)
        {
            items.Add(new XElement("FrameworkReference", new XAttribute("Include", framework)));
        }

        foreach (var analyzer in ProjectAnalyzers.CompilerInputs(r, workspace, analyzerRoots))
        {
            items.Add(new XElement("Analyzer", new XAttribute("Include", Escape(compilerPath(analyzer)))));
        }

        root.Add(items);
        TargetItems.Inject(r, root);
        ProjectRestore.Inject(r, root, workspace, compilerPath);
        // Keep framework declarations unique when both project and BUILD name them.
        root.Add(new XElement("Target", new XAttribute("Name", "BazelUniqueFrameworks"), new XAttribute("BeforeTargets", "ProcessFrameworkReferences;CollectFrameworkReferences"),
            new XElement("RemoveDuplicates", new XAttribute("Inputs", "@(FrameworkReference)"), new XElement("Output", new XAttribute("TaskParameter", "Filtered"), new XAttribute("ItemName", "_BazelFrameworkReferences"))),
            new XElement("ItemGroup", new XElement("FrameworkReference", new XAttribute("Remove", "@(FrameworkReference)")), new XElement("FrameworkReference", new XAttribute("Include", "@(_BazelFrameworkReferences)")))));
        xml.Save(path);
    }
}
