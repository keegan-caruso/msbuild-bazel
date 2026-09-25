using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Xml.Linq;
using Microsoft.Build.Execution;

// Dependency projects publish their evaluated NuGet identity once. Consumers
// supply graph records to NuGet; they never reload dependency SDK projects.
internal sealed record RestoreProject(string Project, string Framework, string Name, string Version, string Assembly, string[] Dependencies, Dictionary<string, string> FrameworkProperties, Dictionary<string, string>? DependencyKeys = null, string? RestoreFramework = null, string? ConfigurationKey = null);
internal static class ProjectRestore
{
    internal static void Export(Session session, ProjectInstance project)
    {
        using var assets = JsonDocument.Parse(File.ReadAllText(Path.Combine(session.State, "obj", "project.assets.json")));
        var value = assets.RootElement.GetProperty("project");
        var properties = new[] { "TargetFrameworkIdentifier", "TargetFrameworkVersion", "TargetFrameworkMoniker", "TargetFrameworkProfile", "TargetPlatformIdentifier", "TargetPlatformVersion", "TargetPlatformMoniker", "TargetPlatformMinVersion" }
            .ToDictionary(name => name, project.GetPropertyValue);
        var request = session.Request;
        var identity = new RestoreProject(request.Project.Path, request.Framework, value.GetProperty("restore").GetProperty("projectName").GetString()!, value.GetProperty("version").GetString()!, request.Assembly, request.Dependencies, properties, DependencyKeys(request), request.Framework, request.RestoreKey);
        File.WriteAllText(Path.Combine(session.State, "project-restore.json"), JsonSerializer.Serialize(identity, Program.Json));
    }
    private static Dictionary<string, string> DependencyKeys(Request request) => request.Dependencies.ToDictionary(
        project => project,
        project => request.DependencyRestoreKeys?[project] ?? throw new InvalidDataException("Missing configured dependency identity: " + project),
        StringComparer.Ordinal);
    private static string Key(RestoreProject project) => project.ConfigurationKey ?? project.Framework + "/" + (project.RestoreFramework ?? project.Framework);
    private static string KeyPath(string key) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(key))).ToLowerInvariant();
    internal static void Inject(Request request, XElement root, string workspace, Func<string, string> compilerPath)
    {
        var projects = new Dictionary<(string Project, string Key), RestoreProject>();
        foreach (var path in request.RestoreProjects ?? [])
        {
            var project = JsonSerializer.Deserialize<RestoreProject>(File.ReadAllText(path), Program.Json)!;
            var key = (project.Project, Key(project));
            if (projects.TryGetValue(key, out var previous) && JsonSerializer.Serialize(previous, Program.Json) != JsonSerializer.Serialize(project, Program.Json))
            {
                throw new InvalidDataException("Conflicting configured restore identity: " + project.Project + " " + project.Framework);
            }

            projects[key] = project;
        }
        if (projects.Count == 0)
        {
            return;
        }

        var canonical = new Dictionary<(string Project, string Key), string>();
        var selectedProjects = new Dictionary<string, RestoreProject>(StringComparer.Ordinal);
        foreach (var file in (request.AssemblySelections ?? []).Select(s => s.RestoreProject).Distinct(StringComparer.Ordinal))
        {
            var selected = JsonSerializer.Deserialize<RestoreProject>(File.ReadAllText(file), Program.Json)!;
            selectedProjects.Add(selected.Assembly, selected);
            foreach (var candidate in projects.Values.Where(p => p.Project == selected.Project && p.Assembly == selected.Assembly))
            {
                if (candidate.Name != selected.Name || candidate.Version != selected.Version)
                {
                    throw new InvalidDataException("Selected project restore identities disagree: " + selected.Project);
                }
                canonical[(candidate.Project, Key(candidate))] = Key(selected);
            }
        }
        string ProjectPath(string name, string framework) => compilerPath(Path.Combine(workspace, ".restore-projects", KeyPath(canonical.GetValueOrDefault((name, framework), framework)), Program.Safe(name)));
        XElement Metadata(string name, string value) => new(name, Program.Escape(value));
        var target = new XElement("Target", new XAttribute("Name", "_BazelRestoreProjectIdentities"), new XAttribute("AfterTargets", "_GenerateRestoreGraph"));
        var items = new XElement("ItemGroup");
        var graphProjects = projects.Values.Where(p => !selectedProjects.TryGetValue(p.Assembly, out var selected) || (p.RestoreFramework ?? p.Framework) != (selected.RestoreFramework ?? selected.Framework) || Key(p) == Key(selected)).ToArray();
        var emittedSpecs = new HashSet<string>(StringComparer.Ordinal);
        foreach (var project in graphProjects)
        {
            var path = ProjectPath(project.Project, Key(project));
            var spec = new XElement("_RestoreGraphEntry", new XAttribute("Include", Program.Escape(path + "#spec")), Metadata("Type", "ProjectSpec"), Metadata("ProjectUniqueName", path), Metadata("ProjectPath", path), Metadata("ProjectName", project.Name), Metadata("Version", project.Version), Metadata("ProjectStyle", "PackageReference"), new XElement("OutputPath", "$(BaseIntermediateOutputPath)restore-projects/" + Program.Escape(KeyPath(Key(project)) + "/" + project.Project) + "/"));
            if (emittedSpecs.Add(path))
            {
                items.Add(spec);
            }
            var framework = new XElement("_RestoreGraphEntry", new XAttribute("Include", Program.Escape(path + "#framework")), Metadata("Type", "TargetFrameworkInformation"), Metadata("ProjectUniqueName", path), Metadata("TargetFramework", project.RestoreFramework ?? project.Framework));
            foreach (var pair in project.FrameworkProperties)
            {
                framework.Add(Metadata(pair.Key, pair.Value));
            }

            items.Add(framework);
        }
        target.Add(items);
        void References(string parent, string framework, IEnumerable<string> dependencies, Dictionary<string, string>? configured)
        {
            foreach (var dependency in dependencies)
            {
                if (configured is null || !configured.TryGetValue(dependency, out var dependencyFramework) || !projects.ContainsKey((dependency, dependencyFramework)))
                {
                    throw new InvalidDataException("Missing configured restore identity: " + dependency);
                }

                target.Add(new XElement("GetRestoreProjectReferencesTask", new XAttribute("ProjectUniqueName", parent), new XAttribute("ParentProjectPath", parent), new XAttribute("ProjectReferences", Program.Escape(ProjectPath(dependency, dependencyFramework))), new XAttribute("TargetFrameworks", Program.Escape(framework)), new XElement("Output", new XAttribute("TaskParameter", "RestoreGraphItems"), new XAttribute("ItemName", "_RestoreGraphEntry"))));
            }
        }
        References("$(MSBuildProjectFullPath)", request.Framework, request.Dependencies, DependencyKeys(request));
        foreach (var project in graphProjects)
        {
            References(Program.Escape(ProjectPath(project.Project, Key(project))), project.RestoreFramework ?? project.Framework, project.Dependencies, project.DependencyKeys);
        }

        root.Add(target);
        var referenceItems = new XElement("ItemGroup");
        foreach (var project in projects.Values.Where(p => !selectedProjects.TryGetValue(p.Assembly, out var selected) || selected.Project == p.Project && Key(selected) == Key(p)))
        {
            var reference = compilerPath(Path.Combine(workspace, ".references", Program.Safe(project.Assembly) + ".dll"));
            referenceItems.Add(new XElement("ReferencePath", new XAttribute("Condition", "'%(ReferencePath.Identity)' == '" + Program.Escape(reference) + "'"), Metadata("ReferenceSourceTarget", "ProjectReference"), Metadata("MSBuildSourceProjectFile", ProjectPath(project.Project, Key(project)))));
        }
        foreach (var runtime in request.RuntimeReferences ?? [])
        {
            var name = Path.GetFileNameWithoutExtension(runtime);
            var matches = selectedProjects.TryGetValue(name, out var selected) ? [selected] : projects.Values.Where(p => p.Assembly == name).ToArray();
            if (matches.Length != 1)
            {
                throw new InvalidDataException("Runtime reference requires one restore identity: " + name);
            }

            var project = matches[0];
            var path = compilerPath(Path.Combine(workspace, ".runtime-references", Path.GetFileName(runtime)));
            referenceItems.Add(new XElement("ReferenceDependencyPaths", new XAttribute("Include", Program.Escape(path)), Metadata("ReferenceSourceTarget", "ProjectReference"), Metadata("MSBuildSourceProjectFile", ProjectPath(project.Project, Key(project))), Metadata("CopyLocal", "true"), Metadata("IncludeRuntimeDependency", "true")));
        }
        root.Add(new XElement("Target", new XAttribute("Name", "_BazelResolvedProjectIdentities"), new XAttribute("AfterTargets", "ResolveAssemblyReferences"), referenceItems));
    }
}
