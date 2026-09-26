using Microsoft.Build.Definition;
using Microsoft.Build.Evaluation;
using Microsoft.Build.Execution;
using Microsoft.Build.Framework;
using Microsoft.Build.Logging;
using static Program;

internal static class ProjectCompilation
{
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
        var properties = BuildProperties.Create(s);
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
        ReferenceProjects.Validate(r, evaluated);
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
}
