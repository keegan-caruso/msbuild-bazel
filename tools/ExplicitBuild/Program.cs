using System.Diagnostics;
using System.Text.Json;
using System.Xml;
using System.Xml.Linq;
using Microsoft.Build.Definition;
using Microsoft.Build.Evaluation;
using Microsoft.Build.Execution;
using Microsoft.Build.Framework;
using Microsoft.Build.Logging;

internal sealed record Input(string Source, string Path);
internal sealed record ProjectAnalyzer(string Project, string Assembly, string[] Directories, PackageInput[]? Packages = null);
internal sealed record Item(string Type, Input File, Dictionary<string, string> Metadata);
internal sealed record Request(Input Project, Input[] Sources, Input[] Imports, Item[] Items, string[] Dependencies, string[] References, string Framework, string[] FrameworkReferences, string Assembly, bool Executable, string Configuration, Dictionary<string, string> Properties, string[] Defines, string Nullable, string LanguageVersion, bool AllowUnsafe, string Runtime, string Reference, string Diagnostics, string SdkVersion, string RuntimeManifest, PackageInput[] Packages, string[] DeclaredPackages, string[] CompilePackages, string[] BuildPackages, string[] AnalyzerPackages, bool ProfileBuild = false, string? RestoreInput = null, bool RestoreOnly = false, Dictionary<string, string>? PackagePrivateAssets = null, ProjectAnalyzer[]? ProjectAnalyzers = null, Dictionary<string, string[]>? TargetExports = null, string? TargetOutput = null, TargetInput[]? TargetInputs = null, string[]? Directories = null, BuildTool[]? BuildTools = null, FileBinding[]? FileBindings = null, Input[]? AdapterImports = null, string[]? GenerateTargets = null, Dictionary<string, string>? GeneratedOutputs = null, Dictionary<string, string>? OutputProperties = null, string[]? ReferencePackages = null, Dictionary<string, string>? DependencyFrameworks = null, string[]? FrameworkAssemblies = null, ProjectOutput[]? ProjectOutputs = null, bool? UseAppHost = null, string? RestoreProjectOutput = null, string[]? RestoreProjects = null, string OutputMode = "sdk", Dictionary<string, Dictionary<string, string>>? DependencyProperties = null, string[]? FrameworkInputs = null, LayoutBinding[]? LayoutBindings = null, string? IdentityOutput = null, Dictionary<string, string[]>? PackageReferencePaths = null, Dictionary<string, string>? DependencyRestoreKeys = null, string[]? RuntimeReferences = null);
internal sealed record Session(Request Request, string Workspace, string State, string Original, string Sdk, string ToolRoot);
internal sealed record Launch(string Entry, string[] Dependencies, string Assembly, bool Test, Input[] Data, PackageInput[]? Packages = null, TestOptions? TestOptions = null, RuntimeHost? RuntimeHost = null);

internal static class Program
{
    internal static readonly JsonSerializerOptions Json = new() { PropertyNameCaseInsensitive = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true };
    private static string ReadPath(string value) => Path.GetFullPath(value);
    internal static string Real(string value)
    {
        var full = Path.GetFullPath(value);
        var current = Path.GetPathRoot(full)!;
        foreach (var part in full[current.Length..].Split(Path.DirectorySeparatorChar, StringSplitOptions.RemoveEmptyEntries))
        {
            current = Path.Combine(current, part);
            var info = new FileInfo(current);
            if (info.LinkTarget is not null)
            {
                current = info.ResolveLinkTarget(true)!.FullName;
            }
        }
        return current;
    }
    private static T Read<T>(string path) => JsonSerializer.Deserialize<T>(File.ReadAllText(path), Json)!;
    internal static string Safe(string value)
    {
        if (string.IsNullOrEmpty(value) || Path.IsPathRooted(value) || value.Contains('\\') || value.Split('/').Any(p => p is "" or "." or "..") || value.IndexOfAny(['\0', '\r', '\n']) >= 0)
        {
            throw new InvalidDataException("Unsafe logical path: " + value);
        }

        return value;
    }
    internal static string Escape(string value) => value.Replace("%", "%25", StringComparison.Ordinal).Replace("$", "%24", StringComparison.Ordinal).Replace("@", "%40", StringComparison.Ordinal).Replace(";", "%3B", StringComparison.Ordinal).Replace("'", "%27", StringComparison.Ordinal).Replace("(", "%28", StringComparison.Ordinal).Replace(")", "%29", StringComparison.Ordinal).Replace("*", "%2A", StringComparison.Ordinal).Replace("?", "%3F", StringComparison.Ordinal);
    internal static void Copy(string source, string target)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        if (File.Exists(target))
        {
            if (!File.ReadAllBytes(source).AsSpan().SequenceEqual(File.ReadAllBytes(target)))
            {
                throw new InvalidDataException("Conflicting runtime/input destination: " + target);
            }

            return;
        }
        File.Copy(source, target);
    }
    public static int Main(string[] args)
    {
        try
        {
            if (args is ["--bazel-worker", var toolInputs, "--persistent_worker"] && toolInputs.StartsWith("--tool-inputs=", StringComparison.Ordinal))
            {
                return LinuxWorker.Run(toolInputs["--tool-inputs=".Length..]).GetAwaiter().GetResult();
            }

            if (args is ["--bazel-worker", var toolArgument, var responseFile] && toolArgument.StartsWith("--tool-inputs=", StringComparison.Ordinal) && responseFile.StartsWith('@'))
            {
                return Build(Read<Request>(File.ReadAllText(responseFile[1..]).Trim()));
            }

            if (args is ["--bazel-worker", "--persistent_worker"])
            {
                return LinuxWorker.Run().GetAwaiter().GetResult();
            }

            if (args is ["--isolated-worker"])
            {
                return LinuxWorker.Child().GetAwaiter().GetResult();
            }

            if (args is ["--bazel-worker", var parameter] && parameter.StartsWith('@'))
            {
                return Build(Read<Request>(File.ReadAllText(parameter[1..]).Trim()));
            }

            if (args is ["pair", var pair])
            {
                AssemblyContracts.Pair(Read<AssemblyPair>(pair));
                return 0;
            }
            if (args is ["layout", var layout])
            {
                ArtifactLayouts.Compose(Read<LayoutRequest>(layout));
                return 0;
            }
            if (args is ["extract", var extraction])
            {
                Package.Extract(Read<PackageRequest>(extraction));
                return 0;
            }
            if (args is ["build", var request])
            {
                return Build(Read<Request>(request));
            }

            if (args is ["compile", var session])
            {
                return Compile(Read<Session>(session));
            }

            if (args.Length >= 2 && args[0] == "run")
            {
                return Run(Read<Launch>(args[1]), args[2..]);
            }

            throw new ArgumentException("Expected build/compile/run request.json");
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
    private static int Build(Request r)
    {
        Safe(r.Assembly);
        if (r.Assembly.Contains('/'))
        {
            throw new InvalidDataException("Assembly name must be a filename");
        }

        var diagnostics = ReadPath(r.Diagnostics);
        Directory.CreateDirectory(diagnostics);
        diagnostics = Real(diagnostics);
        var work = Path.Combine(diagnostics, ".work");
        var workspace = Path.Combine(work, "workspace");
        var state = Path.Combine(work, "state");
        Directory.CreateDirectory(workspace);
        Directory.CreateDirectory(state);
        try
        {
            var session = Prepare(r, workspace, state);
            var sdk = session.Sdk;
            var sessionPath = Path.Combine(state, "session.json");
            File.WriteAllText(sessionPath, JsonSerializer.Serialize(session, Json));
            var roots = Read<string[]>(r.RuntimeManifest);
            var start = Sandbox.Start(workspace, state, roots.Append(sdk).Append(session.ToolRoot).Concat(r.Packages.Select(p => Real(p.Directory))), sdk);
            start.ArgumentList.Add(Path.Combine(sdk, "dotnet"));
            start.ArgumentList.Add(Path.Combine(session.ToolRoot, "ExplicitBuild.dll"));
            start.ArgumentList.Add("compile");
            start.ArgumentList.Add(sessionPath);
            var exit = Execute(start, Path.Combine(diagnostics, "build.log"));
            if (exit != 0)
            {
                return exit;
            }

            Publish(r, state);
            return 0;
        }
        finally
        {
            if (Directory.Exists(work))
            {
                Directory.Delete(work, true);
            }
        }
    }
    internal static Session Prepare(Request r, string workspace, string state, Func<string, string>? compilerPath = null, string[]? analyzerRoots = null)
    {
        compilerPath ??= path => path;
        Safe(r.Assembly);
        FrameworkReferences.Validate(r);
        if (r.Assembly.Contains('/'))
        {
            throw new InvalidDataException("Assembly name must be a filename");
        }

        Directory.CreateDirectory(workspace);
        Directory.CreateDirectory(state);
        foreach (var directory in r.Directories ?? [])
        {
            Directory.CreateDirectory(Path.Combine(workspace, Safe(directory)));
        }

        foreach (var file in r.Sources.Concat(r.Imports).Concat(r.AdapterImports ?? []).Concat(r.Items.Select(i => i.File)).Prepend(r.Project))
        {
            Copy(ReadPath(file.Source), Path.Combine(workspace, Safe(file.Path)));
        }

        var references = Path.Combine(workspace, ".references");
        Directory.CreateDirectory(references);
        foreach (var reference in r.References)
        {
            Copy(ReadPath(reference), Path.Combine(references, Path.GetFileName(reference)));
        }

        foreach (var reference in r.RuntimeReferences ?? [])
        {
            Copy(ReadPath(reference), Path.Combine(workspace, ".runtime-references", Path.GetFileName(reference)));
        }

        ArtifactLayouts.Stage(r, workspace);
        ProjectAnalyzers.Stage(r, workspace, analyzerRoots);
        BuildTools.Stage(r, workspace);
        ProjectOutputs.Stage(r, workspace);
        var project = Path.Combine(workspace, Safe(r.Project.Path));
        var original = Path.Combine(state, "original.xml");
        File.Copy(project, original);
        if (r.RestoreInput is not null || r.RestoreOnly)
        {
            PreparedRestore.Validate(r, original);
        }

        var packageRoot = Path.Combine(workspace, ".nuget", "packages");
        Directory.CreateDirectory(packageRoot);
        foreach (var package in r.Packages)
        {
            var target = Path.Combine(packageRoot, Safe(package.Id.ToLowerInvariant()), Safe(package.Version));
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            Directory.CreateSymbolicLink(target, compilerPath(Real(package.Directory)));
        }
        var config = Path.Combine(workspace, "NuGet.Config");
        if (File.Exists(config))
        {
            throw new InvalidDataException("Explicit builds supply their own closed NuGet configuration");
        }

        File.WriteAllText(config, "<configuration><packageSources><clear /></packageSources></configuration>");
        if (!OperatingSystem.IsWindows())
        {
            File.SetUnixFileMode(project, UnixFileMode.UserRead | UnixFileMode.UserWrite);
        }

        WriteProject(r, project, references, compilerPath, analyzerRoots);
        var session = new Session(r, workspace, state, original, Path.GetDirectoryName(Environment.ProcessPath!)!, Real(AppContext.BaseDirectory.TrimEnd('/')));
        if (r.RestoreInput is not null)
        {
            PreparedRestore.Install(session, compilerPath);
        }

        return session;
    }
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
    private static Dictionary<string, string> Properties(Session s)
    {
        var r = s.Request;
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["TargetFramework"] = r.Framework,
            ["NetCoreSdkRoot"] = Path.Combine(s.Sdk, "sdk", r.SdkVersion),
            ["Configuration"] = r.Configuration,
            ["AssemblyName"] = r.Assembly,
            ["OutputType"] = r.Executable ? "Exe" : "Library",
            ["BaseIntermediateOutputPath"] = Path.Combine(s.State, "obj") + "/",
            ["MSBuildProjectExtensionsPath"] = Path.Combine(s.State, "obj") + "/",
            ["IntermediateOutputPath"] = Path.Combine(s.State, "obj") + "/",
            ["OutputPath"] = Path.Combine(s.State, "out") + "/",
            ["AppendTargetFrameworkToOutputPath"] = "false",
            ["AppendRuntimeIdentifierToOutputPath"] = "false",
            ["UseAppHost"] = r.Executable && (r.UseAppHost ?? true) ? "true" : "false",
            ["BuildProjectReferences"] = "false",
            ["DisableTransitiveProjectReferences"] = "true",
            ["RestoreRecursive"] = "false",
            ["CopyLocalLockFileAssemblies"] = "true",
            ["RestorePackagesPath"] = Path.Combine(s.Workspace, ".nuget/packages"),
            ["RestoreConfigFile"] = Path.Combine(s.Workspace, "NuGet.Config"),
            ["RestoreSources"] = "",
            ["NuGetAudit"] = "false",
            ["RestoreUseStaticGraphEvaluation"] = "false",
            ["UseSharedCompilation"] = LinuxWorker.Isolated ? "true" : "false",
            ["Deterministic"] = "true",
            ["ProduceReferenceAssembly"] = r.OutputMode == "sdk" ? "true" : "false",
            ["ProduceOnlyReferenceAssembly"] = r.OutputMode == "reference" ? "true" : "false",
            ["PathMap"] = s.Workspace + "=/_/workspace," + s.State + "=/_/state",
            ["DebugType"] = "portable",
            ["Nullable"] = r.Nullable,
            ["LangVersion"] = r.LanguageVersion,
            ["AllowUnsafeBlocks"] = r.AllowUnsafe.ToString(),
        };
        if (r.Defines.Length > 0)
        {
            result["DefineConstants"] = string.Join(';', r.Defines);
        }

        if (r.FrameworkInputs is not null)
        {
            result["DisableImplicitFrameworkReferences"] = "true";
            result["NoStdLib"] = "true";
            result["AutomaticallyUseReferenceAssemblyPackages"] = "false";
        }
        foreach (var (name, value) in r.Properties)
        {
            XmlConvert.VerifyNCName(name);
            // Sharing changes compiler process lifetime, not the declared tool or inputs.
            // Permit callers to bound memory for package-provided compiler closures.
            if (name.Equals("UseSharedCompilation", StringComparison.OrdinalIgnoreCase) && bool.TryParse(value, out _))
            {
                result[name] = value;
                continue;
            }
            if (result.ContainsKey(name) || name.StartsWith("MSBuild", StringComparison.OrdinalIgnoreCase) || name.StartsWith("Restore", StringComparison.OrdinalIgnoreCase) || name.Contains("Path", StringComparison.OrdinalIgnoreCase) || name.Contains("Directory", StringComparison.OrdinalIgnoreCase) || value.Contains("$(", StringComparison.Ordinal) || value.Contains('/') || value.Contains('\\'))
            {
                throw new InvalidDataException("Reserved or file-valued MSBuild property: " + name);
            }

            result.Add(name, value);
        }
        ArtifactLayouts.Bind(s, result);
        BuildTools.Bind(s, result);
        GeneratedFiles.Bind(s, result);
        return result;
    }
    private static void WriteProject(Request r, string path, string references, Func<string, string> compilerPath, string[]? analyzerRoots)
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

        foreach (var item in r.Items)
        {
            if (new[] { "ProjectReference", "Reference", "Analyzer", "PackageReference", "FrameworkReference" }.Contains(item.Type, StringComparer.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("Dependency items require typed dependency attributes");
            }

            var itemPath = Path.Combine(workspace, Safe(item.File.Path));
            var include = item.Type is "AdditionalFiles" or "GlobalAnalyzerConfigFiles" or "EditorConfigFiles"
                ? compilerPath(itemPath) : Path.GetRelativePath(Path.GetDirectoryName(path)!, itemPath);
            var element = new XElement(item.Type, new XAttribute("Include", Escape(include)));
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
        foreach (var package in r.Packages.Where(p => r.CompilePackages.Contains(p.Id, StringComparer.OrdinalIgnoreCase)))
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
    private static string? engineRoot;
    internal static int Compile(Session s)
    {
        var sdkRoot = Path.Combine(s.Sdk, "sdk", s.Request.SdkVersion);
        if (engineRoot is null)
        {
            System.Runtime.Loader.AssemblyLoadContext.Default.Resolving += (context, name) => File.Exists(Path.Combine(sdkRoot, name.Name + ".dll")) ? context.LoadFromAssemblyPath(Path.Combine(sdkRoot, name.Name + ".dll")) : null;
            engineRoot = sdkRoot;
        }
        else if (engineRoot != sdkRoot)
        {
            throw new InvalidDataException("A worker cannot change SDK versions");
        }

        Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", Path.Combine(sdkRoot, "MSBuild.dll"));
        Environment.SetEnvironmentVariable("MSBuildSDKsPath", Path.Combine(sdkRoot, "Sdks"));
        return BuildProject(s);
    }
    private static int BuildProject(Session s)
    {
        var profile = s.Request.ProfileBuild ? new CompileProfile() : null;
        var r = s.Request;
        var properties = Properties(s);
        var path = Path.Combine(s.Workspace, Safe(r.Project.Path));
        Environment.CurrentDirectory = Path.GetDirectoryName(path)!;
        // Restore operates only on this declared project; project references have
        // been replaced by Bazel reference outputs before either target executes.
        foreach (var target in r.RestoreOnly ? new[] { "Restore" } : r.RestoreInput is not null ? new[] { "Build" } : new[] { "Restore", "Build" })
        {
            // Bazel replaces the worker when its declared SDK/tools change. Request
            // XML lives at content-identified paths; evaluated/build state stays fresh.
            using var collection = new ProjectCollection(null, null, null, ToolsetDefinitionLocations.Default, 1, false, false, false, reuseProjectRootElementCache: LinuxWorker.Isolated);
            if (profile is not null)
            {
                collection.RegisterLogger(profile);
            }

            profile?.Mark(target + "CollectionSetup");
            var instance = profile is null ? new ProjectInstance(path, properties, null, collection) : ProjectInstance.FromFile(path, new ProjectOptions { GlobalProperties = properties, ProjectCollection = collection, LoadSettings = ProjectLoadSettings.ProfileEvaluation });
            profile?.Mark(target + "Evaluation");
            ConfiguredDependencies.ValidateProducer(r, instance);
            ArtifactLayouts.Validate(s, instance);
            BuildTools.Validate(s, instance);
            GeneratedFiles.Validate(s, instance);
            if (target == "Build")
            {
                FrameworkReferences.ValidateAssemblies(s, instance, requireReferences: true);
            }

            if (target == "Restore" || r.RestoreInput is not null)
            {
                ValidateDeclarations(s, instance);
                profile?.Mark("declarationValidation");
            }
            BuildResult result;
            using (var manager = new BuildManager())
            {
                var parameters = new BuildParameters(collection) { EnableNodeReuse = false, MaxNodeCount = 1, Loggers = profile is null ? [new ConsoleLogger(LoggerVerbosity.Normal)] : [new ConsoleLogger(LoggerVerbosity.Normal), profile] };
                var targets = target == "Build" ? r.GenerateTargets is { Length: > 0 } ? r.GenerateTargets : new[] { target }.Concat(r.TargetExports?.Keys ?? Enumerable.Empty<string>()).ToArray() : [target];
                var request = new BuildRequestData(instance, targets, null, target == "Build" ? BuildRequestDataFlags.ProvideProjectStateAfterBuild : BuildRequestDataFlags.None);
                if (profile is null)
                {
                    result = manager.Build(parameters, request);
                }
                else
                {
                    profile.Mark(target + "ManagerSetup");
                    manager.BeginBuild(parameters);
                    profile.Mark(target + "BeginBuild");
                    try
                    {
                        result = manager.BuildRequest(request);
                        profile.Mark(target + "Request");
                    }
                    finally
                    {
                        manager.EndBuild();
                        profile.Mark(target + "EndBuild");
                    }
                }
            }
            profile?.Mark(target + "ManagerDispose");
            profile?.Save(Path.Combine(s.State, "compile-profile.json"), r.Project.Path);
            if (result.OverallResult != BuildResultCode.Success)
            {
                return 1;
            }

            if (target == "Restore")
            {
                PackageDeclarations.ValidateRestored(s);
            }

            if (target == "Build" && r.GenerateTargets is not { Length: > 0 })
            {
                ProjectRestore.Export(s, result.ProjectStateAfterBuild!);
                TargetItems.Export(s, result);
                RuntimePackages.Export(s, result.ProjectStateAfterBuild!);
            }
        }
        if (r.RestoreOnly)
        {
            PreparedRestore.Export(s);
        }

        return 0;
    }
    private static void ValidateDeclarations(Session s, ProjectInstance evaluated)
    {
        var r = s.Request;
        var path = Path.Combine(s.Workspace, Safe(r.Project.Path));
        if (evaluated.GetPropertyValue("NetCoreSdkRoot") != Path.Combine(s.Sdk, "sdk", r.SdkVersion))
        {
            throw new InvalidDataException("Toolchain SDK root was overridden");
        }

        ProjectAnalyzers.Validate(s, evaluated);
        ReferencePackages.Validate(r, evaluated);
        PackageDeclarations.Validate(r, evaluated);
        var allowedReferences = FrameworkReferences.ValidateAssemblies(s, evaluated);
        allowedReferences.UnionWith(PackageAssemblyReferences.Validate(s, evaluated));
        foreach (var item in evaluated.GetItems("_BazelOriginalReference").Concat(evaluated.GetItems("_BazelOriginalAnalyzer")))
        {
            if (!(item.ItemType == "_BazelOriginalReference" && allowedReferences.Contains(item.EvaluatedInclude)) && !Path.GetFullPath(item.EvaluatedInclude, Path.GetDirectoryName(path)!).StartsWith(s.Sdk + "/", StringComparison.Ordinal))
            {
                throw new InvalidDataException("Undeclared assembly/analyzer dependency: " + item.EvaluatedInclude);
            }
        }

        var supplied = r.Sources.Select(f => Path.GetFullPath(Path.Combine(s.Workspace, Safe(f.Path)))).ToHashSet(StringComparer.Ordinal);
        var packageRoots = r.Packages.Select(p => Path.Combine(s.Workspace, ".nuget/packages", p.Id.ToLowerInvariant(), p.Version) + "/").ToArray();
        foreach (var item in evaluated.GetItems("_BazelOriginalCompile"))
        {
            var full = Path.GetFullPath(item.EvaluatedInclude, Path.GetDirectoryName(path)!);
            if (!supplied.Contains(full) && !packageRoots.Any(root => full.StartsWith(root, StringComparison.Ordinal)))
            {
                throw new InvalidDataException("Undeclared Compile input: " + item.EvaluatedInclude);
            }
        }
        var frameworks = evaluated.GetItems("_BazelOriginalFrameworkReference").Where(i => !i.GetMetadataValue("IsImplicitlyDefined").Equals("true", StringComparison.OrdinalIgnoreCase)).Select(i => i.EvaluatedInclude).ToHashSet(StringComparer.Ordinal);
        if (!frameworks.IsSubsetOf(r.FrameworkReferences.ToHashSet(StringComparer.Ordinal)))
        {
            throw new InvalidDataException("Undeclared FrameworkReference");
        }
    }
    private static int Execute(ProcessStartInfo start, string? log = null)
    {
        start.RedirectStandardOutput = true;
        start.RedirectStandardError = true;
        using var process = Process.Start(start)!;
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        process.WaitForExit();
        Task.WaitAll(stdout, stderr);
        if (log is not null)
        {
            File.WriteAllText(log, stdout.Result + stderr.Result);
        }

        Console.Write(stdout.Result);
        Console.Error.Write(stderr.Result);
        return process.ExitCode;
    }
    private static int Run(Launch request, string[] args)
    {
        if (request.Test)
        {
            TestExecution.Validate(request.TestOptions ?? new());
        }

        var root = Environment.GetEnvironmentVariable("RULES_MSBUILD_RUNFILES") ?? throw new InvalidDataException("Missing runfiles root");
        var temporary = Path.Combine(Environment.GetEnvironmentVariable("TEST_TMPDIR") ?? Path.GetTempPath(), "msbuild-run-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temporary);
        try
        {
            var entryPackages = RuntimePackages.Read(Path.Combine(root, Safe(request.Entry)));
            var packageInputs = (request.Packages ?? []).Select(p => p with { Directory = Path.Combine(root, Safe(p.Directory)) }).ToArray();
            foreach (var directory in request.Dependencies.Prepend(request.Entry))
            {
                var input = Path.Combine(root, Safe(directory));
                var packages = RuntimePackages.Read(input);
                foreach (var file in RuntimePackages.Files(input, packageInputs))
                {
                    var relative = file.Path;
                    if (directory != request.Entry && entryPackages.TryGetValue(relative, out var selected) && packages.TryGetValue(relative, out var inherited) && selected.Equals(inherited, StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    Copy(file.Source, Path.Combine(temporary, relative));
                }
            }
            foreach (var file in request.Data)
            {
                Copy(Path.Combine(root, Safe(file.Source)), Path.Combine(temporary, Safe(file.Path)));
            }

            var hostRoot = request.RuntimeHost is null ? Path.GetDirectoryName(Environment.ProcessPath!)! : Path.Combine(root, Safe(request.RuntimeHost.Directory));
            var host = request.RuntimeHost is null ? Environment.ProcessPath! : Path.Combine(hostRoot, Safe(request.RuntimeHost.EntryPoint));
            if (!File.Exists(host))
            {
                throw new InvalidDataException("Missing declared runtime host: " + host);
            }

            var start = new ProcessStartInfo(host) { WorkingDirectory = temporary };
            start.Environment["DOTNET_ROOT"] = hostRoot;
            start.Environment["DOTNET_HOST_PATH"] = host;
            foreach (var architecture in new[] { "X64", "X86", "ARM", "ARM64" })
            {
                start.Environment["DOTNET_ROOT_" + architecture] = hostRoot;
            }

            start.Environment["DOTNET_MULTILEVEL_LOOKUP"] = "0";
            start.ArgumentList.Add(Path.Combine(temporary, Safe(request.Assembly) + ".dll"));
            foreach (var arg in args)
            {
                start.ArgumentList.Add(arg);
            }

            if (request.Test)
            {
                return TestExecution.Run(start, request.TestOptions ?? new(), root);
            }

            using var process = Process.Start(start)!;
            using var interrupt = System.Runtime.InteropServices.PosixSignalRegistration.Create(System.Runtime.InteropServices.PosixSignal.SIGTERM, context => { context.Cancel = true; if (!process.HasExited) { process.Kill(true); } });
            process.WaitForExit();
            return process.ExitCode;
        }
        finally { Directory.Delete(temporary, true); }
    }
}
