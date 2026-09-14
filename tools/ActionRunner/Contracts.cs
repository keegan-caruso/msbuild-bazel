namespace ActionRunner;

internal enum ProjectKind { Shared, App }

internal sealed record InputFile(string Source, string Destination);

internal sealed record ActionRequest(
    ProjectKind Project, InputFile[] Sources, string[] Restore, InputFile[] Packages,
    string? PackageManifest, string Plugin, string BuildProps, string BuildTargets, string Output, string Diagnostics,
    string? Dependency, string UndeclaredProbe, string? NativeManifest, InputFile[] NativeFiles,
    string? LoaderJit = null, string? LoaderManifest = null,
    string? GraphProject = null, string[]? GraphDependencies = null, Dictionary<string, string>? GraphGlobalProperties = null, string? GraphAssetsFile = null, string[]? GraphOutputDirectories = null, Dictionary<string, GraphFrameworkSelection>? GraphFrameworkSelections = null, string SdkVersion = "10.0.400");

internal sealed record Artifact(string Path, long Size, string Sha256);
internal sealed record PackageFile(string Path, long Size, string Sha256);
internal sealed record Package(string Id, string Version, string Path, PackageFile[] Files);
internal sealed record PackageManifest(int SchemaVersion, Package[] Packages);
internal sealed record NativeManifest(int SchemaVersion, Artifact[] Files);

internal sealed record RestoreAssets(Dictionary<string, RestoreLibrary> Libraries);
internal sealed record RestoreLibrary(string Type, string? Path = null, string? Sha512 = null);

internal sealed record BuildReport(ProjectKind Project, string Workspace, string[] Command, string[] Packages,
    string[] PackageTargets, int Returncode, string[] CompiledProjects, string[] ReplayHits, string[] SharedSources);

internal sealed record GraphFrameworkSelection(string TargetFramework, Dictionary<string, string> References, bool RemoveFrameworkGlobal = false, string? Project = null);
