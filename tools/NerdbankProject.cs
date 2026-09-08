using Microsoft.Build.Execution;

// The pinned package's computation-only project stays inside its owning action.
// This is not permission for arbitrary disabled/custom-target project references.
internal static class NerdbankProject
{
    public static bool IsProject(string path, string packageRoot) =>
        Path.GetFullPath(path).Equals(Path.GetFullPath(Path.Combine(packageRoot,
            "nerdbank.gitversioning/3.9.50/build/PrivateP2PCaching.proj")),
            OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal);

    public static bool IsReference(ProjectItemInstance reference)
    {
        var project = reference.Project;
        var root = project.GetPropertyValue("RestorePackagesPath");
        if (string.IsNullOrEmpty(root) || !IsProject(reference.GetMetadataValue("FullPath"), root)) return false;
        return reference.GetMetadataValue("NBGV_InnerProject").Equals("true", StringComparison.OrdinalIgnoreCase) &&
            reference.GetMetadataValue("BuildReference").Equals("false", StringComparison.OrdinalIgnoreCase) &&
            reference.GetMetadataValue("ReferenceOutputAssembly").Equals("false", StringComparison.OrdinalIgnoreCase) &&
            reference.GetMetadataValue("Targets") == "GetBuildVersion_Properties;GetBuildVersion_CloudBuildVersionVars" &&
            reference.GetMetadataValue("PrivateAssets").Equals("all", StringComparison.OrdinalIgnoreCase) &&
            reference.GetMetadataValue("OutputItemType").Length == 0 &&
            project.GetPropertyValue("NBGV_PrivateP2PAuxTargets").Length == 0;
    }
}
