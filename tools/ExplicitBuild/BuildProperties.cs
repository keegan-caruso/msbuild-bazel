using System.Xml;

internal static class BuildProperties
{
    internal static Dictionary<string, string> Create(Session s)
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
}
