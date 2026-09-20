using System.Diagnostics;
using System.Text.Json;
using System.Xml;
using System.Xml.Linq;
using Microsoft.Build.Construction;
using Microsoft.Build.Evaluation;
using Microsoft.Build.Execution;
using Microsoft.Build.Framework;
using Microsoft.Build.Logging;

internal sealed record Input(string Source, string Path);
internal sealed record Item(string Type, Input File, Dictionary<string, string> Metadata);
internal sealed record Request(Input Project, Input[] Sources, Input[] Imports, Item[] Items, string[] Dependencies, string[] References, string Framework, string[] FrameworkReferences, string Assembly, bool Executable, string Configuration, Dictionary<string, string> Properties, string[] Defines, string Nullable, string LanguageVersion, bool AllowUnsafe, string Runtime, string Reference, string Diagnostics, string SdkVersion, string RuntimeManifest, PackageInput[] Packages, string[] DeclaredPackages, string[] CompilePackages, string[] BuildPackages, string[] AnalyzerPackages);
internal sealed record Session(Request Request, string Workspace, string State, string Original, string Sdk, string ToolRoot);
internal sealed record Launch(string Entry, string[] Dependencies, string Assembly, bool Test, Input[] Data);

internal static class Program
{
    private static readonly JsonSerializerOptions Json = new() { PropertyNameCaseInsensitive = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true };
    private static string ReadPath(string value) => Path.GetFullPath(value);
    private static string Real(string value)
    {
        var full = Path.GetFullPath(value); var current = Path.GetPathRoot(full)!;
        foreach (var part in full[current.Length..].Split(Path.DirectorySeparatorChar, StringSplitOptions.RemoveEmptyEntries))
        {
            current = Path.Combine(current, part);
            var info = new FileInfo(current);
            if (info.LinkTarget is not null) current = info.ResolveLinkTarget(true)!.FullName;
        }
        return current;
    }
    private static T Read<T>(string path) => JsonSerializer.Deserialize<T>(File.ReadAllText(path), Json)!;
    internal static string Safe(string value)
    {
        if (string.IsNullOrEmpty(value) || Path.IsPathRooted(value) || value.Contains('\\') || value.Split('/').Any(p => p is "" or "." or "..") || value.IndexOfAny(['\0', '\r', '\n']) >= 0)
            throw new InvalidDataException("Unsafe logical path: " + value);
        return value;
    }
    internal static string Escape(string value) => value.Replace("%", "%25", StringComparison.Ordinal).Replace("$", "%24", StringComparison.Ordinal).Replace("@", "%40", StringComparison.Ordinal).Replace(";", "%3B", StringComparison.Ordinal).Replace("'", "%27", StringComparison.Ordinal).Replace("(", "%28", StringComparison.Ordinal).Replace(")", "%29", StringComparison.Ordinal).Replace("*", "%2A", StringComparison.Ordinal).Replace("?", "%3F", StringComparison.Ordinal);
    private static void Copy(string source, string target)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        if (File.Exists(target))
        {
            if (!File.ReadAllBytes(source).AsSpan().SequenceEqual(File.ReadAllBytes(target))) throw new InvalidDataException("Conflicting runtime/input destination: " + target);
            return;
        }
        File.Copy(source, target);
    }
    public static int Main(string[] args)
    {
        try
        {
            if (args is ["extract", var extraction]) { Package.Extract(Read<PackageRequest>(extraction)); return 0; }
            if (args is ["build", var request]) return Build(Read<Request>(request));
            if (args is ["compile", var session]) return Compile(Read<Session>(session));
            if (args.Length >= 2 && args[0] == "run") return Run(Read<Launch>(args[1]), args[2..]);
            throw new ArgumentException("Expected build/compile/run request.json");
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
    private static int Build(Request r)
    {
        Safe(r.Assembly);
        if (r.Assembly.Contains('/')) throw new InvalidDataException("Assembly name must be a filename");
        var diagnostics = ReadPath(r.Diagnostics); Directory.CreateDirectory(diagnostics); diagnostics = Real(diagnostics);
        var work = Path.Combine(diagnostics, ".work"); var workspace = Path.Combine(work, "workspace"); var state = Path.Combine(work, "state");
        Directory.CreateDirectory(workspace); Directory.CreateDirectory(state);
        try
        {
            foreach (var file in r.Sources.Concat(r.Imports).Concat(r.Items.Select(i => i.File)).Prepend(r.Project)) Copy(ReadPath(file.Source), Path.Combine(workspace, Safe(file.Path)));
            var references = Path.Combine(workspace, ".references"); Directory.CreateDirectory(references);
            foreach (var reference in r.References) Copy(ReadPath(reference), Path.Combine(references, Path.GetFileName(reference)));
            var project = Path.Combine(workspace, Safe(r.Project.Path));
            var original = Path.Combine(state, "original.xml"); File.Copy(project, original);
            var packageRoot = Path.Combine(workspace, ".nuget", "packages"); Directory.CreateDirectory(packageRoot);
            foreach (var package in r.Packages)
            {
                var target = Path.Combine(packageRoot, Safe(package.Id.ToLowerInvariant()), Safe(package.Version));
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                Directory.CreateSymbolicLink(target, Real(package.Directory));
            }
            var config = Path.Combine(workspace, "NuGet.Config");
            if (File.Exists(config)) throw new InvalidDataException("Explicit builds supply their own closed NuGet configuration");
            File.WriteAllText(config, "<configuration><packageSources><clear /></packageSources></configuration>");
            WriteProject(r, project, state, references);
            var sdk = Path.GetDirectoryName(Environment.ProcessPath!)!;
            var session = new Session(r, workspace, state, original, sdk, Real(AppContext.BaseDirectory.TrimEnd('/')));
            var sessionPath = Path.Combine(state, "session.json"); File.WriteAllText(sessionPath, JsonSerializer.Serialize(session, Json));
            var roots = Read<string[]>(r.RuntimeManifest);
            var start = Sandbox.Start(workspace, state, roots.Append(sdk).Append(session.ToolRoot).Concat(r.Packages.Select(p => Real(p.Directory))), sdk);
            start.ArgumentList.Add(Path.Combine(sdk, "dotnet")); start.ArgumentList.Add(Path.Combine(session.ToolRoot, "ExplicitBuild.dll")); start.ArgumentList.Add("compile"); start.ArgumentList.Add(sessionPath);
            var exit = Execute(start, Path.Combine(diagnostics, "build.log"));
            if (exit != 0) return exit;
            var output = Path.Combine(state, "out"); var runtime = ReadPath(r.Runtime); Directory.CreateDirectory(runtime);
            var referenceNames = r.References.Select(Path.GetFileName).ToHashSet(StringComparer.Ordinal);
            if (referenceNames.Contains(r.Assembly + ".dll")) throw new InvalidDataException("Dependency assembly name conflicts with this project");
            foreach (var file in Directory.GetFiles(output, "*", SearchOption.AllDirectories))
                if (!referenceNames.Contains(Path.GetRelativePath(output, file))) Copy(file, Path.Combine(runtime, Path.GetRelativePath(output, file)));
            Copy(Path.Combine(state, "obj", "ref", r.Assembly + ".dll"), ReadPath(r.Reference));
            File.WriteAllText(Path.Combine(diagnostics, "report.json"), JsonSerializer.Serialize(new { accepted = true, discovery = false, project = r.Project.Path }, Json));
            return 0;
        }
        finally { if (Directory.Exists(work)) Directory.Delete(work, true); }
    }
    private static Dictionary<string, string> Properties(Session s)
    {
        var r = s.Request;
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["TargetFramework"] = r.Framework,
            ["Configuration"] = r.Configuration,
            ["AssemblyName"] = r.Assembly,
            ["OutputType"] = r.Executable ? "Exe" : "Library",
            ["BaseIntermediateOutputPath"] = Path.Combine(s.State, "obj") + "/",
            ["MSBuildProjectExtensionsPath"] = Path.Combine(s.State, "obj") + "/",
            ["IntermediateOutputPath"] = Path.Combine(s.State, "obj") + "/",
            ["OutputPath"] = Path.Combine(s.State, "out") + "/",
            ["AppendTargetFrameworkToOutputPath"] = "false",
            ["AppendRuntimeIdentifierToOutputPath"] = "false",
            ["UseAppHost"] = r.Executable ? "true" : "false",
            ["BuildProjectReferences"] = "false",
            ["RestoreRecursive"] = "false",
            ["CopyLocalLockFileAssemblies"] = "true",
            ["RestorePackagesPath"] = Path.Combine(s.Workspace, ".nuget/packages"),
            ["RestoreConfigFile"] = Path.Combine(s.Workspace, "NuGet.Config"),
            ["RestoreSources"] = "",
            ["NuGetAudit"] = "false",
            ["RestoreUseStaticGraphEvaluation"] = "false",
            ["UseSharedCompilation"] = "false",
            ["Deterministic"] = "true",
            ["ProduceReferenceAssembly"] = "true",
            ["PathMap"] = s.Workspace + "=/_/workspace," + s.State + "=/_/state",
            ["DebugType"] = "portable",
            ["Nullable"] = r.Nullable,
            ["LangVersion"] = r.LanguageVersion,
            ["AllowUnsafeBlocks"] = r.AllowUnsafe.ToString(),
        };
        if (r.Defines.Length > 0) result["DefineConstants"] = string.Join(';', r.Defines);
        foreach (var (name, value) in r.Properties)
        {
            XmlConvert.VerifyNCName(name);
            if (result.ContainsKey(name) || name.StartsWith("MSBuild", StringComparison.OrdinalIgnoreCase) || name.StartsWith("Restore", StringComparison.OrdinalIgnoreCase) || name.Contains("Path", StringComparison.OrdinalIgnoreCase) || name.Contains("Directory", StringComparison.OrdinalIgnoreCase) || value.Contains("$(", StringComparison.Ordinal) || value.Contains('/') || value.Contains('\\')) throw new InvalidDataException("Reserved or file-valued MSBuild property: " + name);
            result.Add(name, value);
        }
        return result;
    }
    private static void WriteProject(Request r, string path, string state, string references)
    {
        var xml = XDocument.Load(path); var root = xml.Root!;
        if (root.Name != "Project" || root.Elements("Sdk").Any() || root.Attribute("Sdk") is not { } sdk || sdk.Value.Contains(';')) throw new InvalidDataException("Initial explicit rules require one root Project Sdk attribute");
        var sdkName = sdk.Value; sdk.Remove();
        root.AddFirst(new XElement("Import", new XAttribute("Project", "Sdk.props"), new XAttribute("Sdk", sdkName)));
        root.Add(new XElement("Import", new XAttribute("Project", "Sdk.targets"), new XAttribute("Sdk", sdkName)));
        var items = new XElement("ItemGroup");
        foreach (var type in r.Items.Select(i => i.Type).Concat(["Compile", "ProjectReference", "Reference", "PackageReference"]).Distinct(StringComparer.OrdinalIgnoreCase))
        {
            XmlConvert.VerifyNCName(type);
            if (type is "FrameworkReference") throw new InvalidDataException("Use dependency attributes for " + type);
            items.Add(new XElement(type, new XAttribute("Remove", "@(" + type + ")")));
        }
        var workspace = path[..^Safe(r.Project.Path).Length];
        foreach (var source in r.Sources) items.Add(new XElement("Compile", new XAttribute("Include", Escape(Path.Combine(workspace, Safe(source.Path))))));
        foreach (var item in r.Items)
        {
            if (item.Type is "ProjectReference" or "Reference" or "Analyzer" or "PackageReference" or "FrameworkReference") throw new InvalidDataException("Dependency items require typed dependency attributes");
            var element = new XElement(item.Type, new XAttribute("Include", Escape(Path.Combine(workspace, Safe(item.File.Path)))));
            foreach (var (name, value) in item.Metadata)
            {
                XmlConvert.VerifyNCName(name);
                if (name.Equals("FullPath", StringComparison.OrdinalIgnoreCase) || value.Contains("$(", StringComparison.Ordinal) || value.Contains("@(", StringComparison.Ordinal) || Path.IsPathRooted(value)) throw new InvalidDataException("Unsafe item metadata: " + name);
                element.Add(new XElement(name, Escape(value)));
            }
            items.Add(element);
        }
        foreach (var reference in Directory.GetFiles(references)) items.Add(new XElement("Reference", new XAttribute("Include", Path.GetFileNameWithoutExtension(reference)), new XElement("HintPath", Escape(reference)), new XElement("Private", "true")));
        foreach (var package in r.Packages)
        {
            var excluded = new List<string>();
            if (!r.CompilePackages.Contains(package.Id, StringComparer.OrdinalIgnoreCase)) excluded.AddRange(["compile", "runtime", "native", "contentFiles"]);
            if (!r.BuildPackages.Contains(package.Id, StringComparer.OrdinalIgnoreCase)) excluded.AddRange(["build", "buildTransitive", "buildMultitargeting"]);
            if (!r.AnalyzerPackages.Contains(package.Id, StringComparer.OrdinalIgnoreCase)) excluded.Add("analyzers");
            items.Add(new XElement("PackageReference", new XAttribute("Include", package.Id), new XAttribute("Version", "[" + package.Version + "]"), new XAttribute("ExcludeAssets", string.Join(';', excluded))));
        }
        foreach (var framework in r.FrameworkReferences) items.Add(new XElement("FrameworkReference", new XAttribute("Include", framework)));
        root.Add(items);
        // Keep framework declarations unique when both project and BUILD name them.
        root.Add(new XElement("Target", new XAttribute("Name", "BazelUniqueFrameworks"), new XAttribute("BeforeTargets", "ProcessFrameworkReferences;CollectFrameworkReferences"),
            new XElement("RemoveDuplicates", new XAttribute("Inputs", "@(FrameworkReference)"), new XElement("Output", new XAttribute("TaskParameter", "Filtered"), new XAttribute("ItemName", "_BazelFrameworkReferences"))),
            new XElement("ItemGroup", new XElement("FrameworkReference", new XAttribute("Remove", "@(FrameworkReference)")), new XElement("FrameworkReference", new XAttribute("Include", "@(_BazelFrameworkReferences)")))));
        xml.Save(path);
    }
    private static int Compile(Session s)
    {
        var sdkRoot = Path.Combine(s.Sdk, "sdk", s.Request.SdkVersion);
        System.Runtime.Loader.AssemblyLoadContext.Default.Resolving += (context, name) => File.Exists(Path.Combine(sdkRoot, name.Name + ".dll")) ? context.LoadFromAssemblyPath(Path.Combine(sdkRoot, name.Name + ".dll")) : null;
        Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", Path.Combine(sdkRoot, "MSBuild.dll"));
        Environment.SetEnvironmentVariable("MSBuildSDKsPath", Path.Combine(sdkRoot, "Sdks"));
        return BuildProject(s);
    }
    private static int BuildProject(Session s)
    {
        var r = s.Request; var properties = Properties(s); var path = Path.Combine(s.Workspace, Safe(r.Project.Path));
        using (var collection = new ProjectCollection())
        {
            using var reader = XmlReader.Create(s.Original, new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit });
            var root = ProjectRootElement.Create(reader, collection); root.FullPath = path;
            var evaluated = new Project(root, properties, null, collection);
            var actual = evaluated.GetItems("ProjectReference").Select(i => Path.GetRelativePath(s.Workspace, Path.GetFullPath(i.EvaluatedInclude.Replace('\\', '/'), Path.GetDirectoryName(path)!))).ToHashSet(StringComparer.Ordinal);
            if (!actual.SetEquals(r.Dependencies)) throw new InvalidDataException("ProjectReference declarations disagree with Bazel deps: " + string.Join(',', actual));
            foreach (var dependency in evaluated.GetItems("ProjectReference"))
            {
                foreach (var name in new[] { "Aliases", "SetTargetFramework", "SetConfiguration", "AdditionalProperties", "GlobalPropertiesToRemove", "OutputItemType" })
                    if (dependency.GetMetadataValue(name).Length > 0) throw new InvalidDataException("Unsupported ProjectReference metadata: " + name);
                foreach (var name in new[] { "ReferenceOutputAssembly", "BuildReference" })
                    if (dependency.GetMetadataValue(name) is { Length: > 0 } value && !value.Equals("true", StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Unsupported ProjectReference metadata: " + name);
            }
            foreach (var package in evaluated.GetItems("PackageReference"))
            {
                var declared = r.Packages.SingleOrDefault(p => p.Id.Equals(package.EvaluatedInclude, StringComparison.OrdinalIgnoreCase));
                if (declared is null || !r.DeclaredPackages.Contains(declared.Id, StringComparer.OrdinalIgnoreCase)) throw new InvalidDataException("Undeclared PackageReference: " + package.EvaluatedInclude);
                foreach (var name in new[] { "IncludeAssets", "ExcludeAssets", "Aliases", "VersionOverride", "GeneratePathProperty" })
                    if (package.GetMetadataValue(name).Length > 0) throw new InvalidDataException("Use explicit package roles; unsupported PackageReference metadata: " + name);
                var version = package.GetMetadataValue("Version");
                if (version.Length > 0 && version != declared.Version && version != "[" + declared.Version + "]") throw new InvalidDataException("PackageReference version disagrees with lock: " + package.EvaluatedInclude);
                if (package.GetMetadataValue("PrivateAssets") is { Length: > 0 } privacy && !privacy.Equals("none", StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("PrivateAssets package propagation is not qualified in this slice");
            }
            foreach (var item in evaluated.GetItems("Reference").Concat(evaluated.GetItems("Analyzer")))
                if (!Path.GetFullPath(item.EvaluatedInclude, Path.GetDirectoryName(path)!).StartsWith(s.Sdk + "/", StringComparison.Ordinal)) throw new InvalidDataException("Undeclared assembly/analyzer dependency: " + item.EvaluatedInclude);
            var supplied = r.Sources.Select(f => Path.GetFullPath(Path.Combine(s.Workspace, Safe(f.Path)))).ToHashSet(StringComparer.Ordinal);
            foreach (var item in evaluated.GetItems("Compile"))
                if (!supplied.Contains(Path.GetFullPath(item.EvaluatedInclude, Path.GetDirectoryName(path)!))) throw new InvalidDataException("Undeclared Compile input: " + item.EvaluatedInclude);
            var frameworks = evaluated.GetItems("FrameworkReference").Where(i => !i.GetMetadataValue("IsImplicitlyDefined").Equals("true", StringComparison.OrdinalIgnoreCase)).Select(i => i.EvaluatedInclude).ToHashSet(StringComparer.Ordinal);
            if (!frameworks.IsSubsetOf(r.FrameworkReferences.ToHashSet(StringComparer.Ordinal))) throw new InvalidDataException("Undeclared FrameworkReference");
        }
        // Restore operates only on this declared project; project references have
        // been replaced by Bazel reference outputs before either target executes.
        foreach (var target in new[] { "Restore", "Build" })
        {
            using var collection = new ProjectCollection();
            var instance = new ProjectInstance(path, properties, null, collection);
            using var manager = new BuildManager();
            var result = manager.Build(new BuildParameters(collection) { EnableNodeReuse = false, MaxNodeCount = 1, Loggers = [new ConsoleLogger(LoggerVerbosity.Normal)] }, new BuildRequestData(instance, [target]));
            if (result.OverallResult != BuildResultCode.Success) return 1;
        }
        return 0;
    }
    private static int Execute(ProcessStartInfo start, string? log = null)
    {
        start.RedirectStandardOutput = true; start.RedirectStandardError = true;
        using var process = Process.Start(start)!;
        var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
        process.WaitForExit(); Task.WaitAll(stdout, stderr);
        if (log is not null) File.WriteAllText(log, stdout.Result + stderr.Result);
        Console.Write(stdout.Result); Console.Error.Write(stderr.Result);
        return process.ExitCode;
    }
    private static int Run(Launch request, string[] args)
    {
        if (request.Test && (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("TESTBRIDGE_TEST_ONLY")) || int.TryParse(Environment.GetEnvironmentVariable("TEST_TOTAL_SHARDS"), out var count) && count > 1)) throw new InvalidDataException("Executable test filtering/sharding is not supported");
        var root = Environment.GetEnvironmentVariable("RULES_MSBUILD_RUNFILES") ?? throw new InvalidDataException("Missing runfiles root");
        var temporary = Path.Combine(Environment.GetEnvironmentVariable("TEST_TMPDIR") ?? Path.GetTempPath(), "msbuild-run-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(temporary);
        try
        {
            foreach (var directory in request.Dependencies.Prepend(request.Entry))
            {
                var input = Path.Combine(root, Safe(directory));
                foreach (var file in Directory.GetFiles(input, "*", SearchOption.AllDirectories)) Copy(file, Path.Combine(temporary, Path.GetRelativePath(input, file)));
            }
            foreach (var file in request.Data) Copy(Path.Combine(root, Safe(file.Source)), Path.Combine(temporary, Safe(file.Path)));
            var start = new ProcessStartInfo(Environment.ProcessPath!) { WorkingDirectory = temporary };
            start.Environment["DOTNET_ROOT"] = Path.GetDirectoryName(Environment.ProcessPath!)!;
            start.Environment["DOTNET_MULTILEVEL_LOOKUP"] = "0";
            start.ArgumentList.Add(Path.Combine(temporary, Safe(request.Assembly) + ".dll")); foreach (var arg in args) start.ArgumentList.Add(arg);
            using var process = Process.Start(start)!;
            using var interrupt = System.Runtime.InteropServices.PosixSignalRegistration.Create(System.Runtime.InteropServices.PosixSignal.SIGTERM, context => { context.Cancel = true; if (!process.HasExited) process.Kill(true); });
            process.WaitForExit(); return process.ExitCode;
        }
        finally { Directory.Delete(temporary, true); }
    }
}
