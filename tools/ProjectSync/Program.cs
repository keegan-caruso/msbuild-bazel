namespace RulesMSBuild.ProjectSync;

internal static class Program
{
    public static int Main(string[] args)
    {
        try
        {
            if (args.Length != 0 && args[0] == "publish")
            {
                PreparedSync.Publish(args[1..]);
                return 0;
            }
            if (args.Length == 3 && args[0] == "stage")
            {
                PreparedSync.Stage(args[1], args[2]);
                return 0;
            }
            if (args.Length != 0 && args[0] == "nuget-update")
            {
                NuGetUpdate.Run(args[1..]).GetAwaiter().GetResult();
                return 0;
            }
            if (args.Length < 3)
            {
                throw new ArgumentException("ProjectSync <workspace> <sdk-directory> <project.csproj|project.ilproj|dirs.proj>... [--check] [--configuration Release] [--framework TFM] [--package-build] [--resolve-references] [--package-input FILE] [--mappings mappings.json] [--qualification-cache DIR [--qualification-cache-url URL]]");
            }
            using var profile = SyncProfile.Measure("sync-total");
            var sdk = WorkspaceView.PhysicalPath(args[1]);
            if (!File.Exists(Path.Combine(sdk, "MSBuild.dll")))
            {
                throw new ArgumentException("sdk-directory must contain MSBuild.dll");
            }
            System.Runtime.Loader.AssemblyLoadContext.Default.Resolving += (context, name) => File.Exists(Path.Combine(sdk, name.Name + ".dll")) ? context.LoadFromAssemblyPath(Path.Combine(sdk, name.Name + ".dll")) : null;
            Environment.SetEnvironmentVariable("DOTNET_HOST_PATH", Path.Combine(Path.GetDirectoryName(Path.GetDirectoryName(sdk))!, OperatingSystem.IsWindows() ? "dotnet.exe" : "dotnet"));
            Environment.SetEnvironmentVariable("MSBuildEnableWorkloadResolver", "false");
            Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", Path.Combine(sdk, "MSBuild.dll"));
            Environment.SetEnvironmentVariable("MSBuildSDKsPath", Path.Combine(sdk, "Sdks"));
            var projects = new List<string>();
            string? mappings = null;
            var check = false;
            var packageBuild = false;
            var resolveReferences = false;
            string? qualificationDirectory = null;
            string? qualificationUrl = null;
            var packageInputs = new List<string>();
            var configuration = "Release";
            var framework = "";
            string? inputs = null;
            string? runfiles = null;
            for (var i = 2; i < args.Length; i++)
            {
                if (args[i] == "--check")
                {
                    check = true;
                }
                else if (args[i] == "--package-build")
                {
                    packageBuild = true;
                }
                else if (args[i] == "--resolve-references")
                {
                    resolveReferences = true;
                }
                else if (args[i] is "--qualification-cache" or "--qualification-cache-url")
                {
                    var option = args[i];
                    if (++i == args.Length || args[i].Length == 0)
                    {
                        throw new ArgumentException(option + " requires a value");
                    }
                    if (option == "--qualification-cache")
                    {
                        qualificationDirectory = Path.GetFullPath(args[i]);
                    }
                    else
                    {
                        qualificationUrl = args[i];
                    }
                }
                else if (args[i] == "--package-input")
                {
                    if (++i == args.Length)
                    {
                        throw new ArgumentException("--package-input requires a workspace-relative file");
                    }
                    packageInputs.Add(WorkspaceView.Safe(args[i]));
                }
                else if (args[i] is "--configuration" or "--framework")
                {
                    var option = args[i];
                    if (++i == args.Length || args[i].Length == 0 || args[i].Any(c => !char.IsAsciiLetterOrDigit(c) && c is not '.' and not '_' and not '-'))
                    {
                        throw new ArgumentException(option + " requires a nonempty name using letters, digits, dots, underscores or hyphens");
                    }
                    if (option == "--configuration")
                    {
                        configuration = args[i];
                    }
                    else
                    {
                        framework = args[i];
                    }
                }
                else if (args[i] is "--inputs" or "--runfiles")
                {
                    var option = args[i];
                    if (++i == args.Length)
                    {
                        throw new ArgumentException(option + " requires a path");
                    }
                    if (option == "--inputs")
                    {
                        inputs = Path.GetFullPath(args[i]);
                    }
                    else
                    {
                        runfiles = Path.GetFullPath(args[i]);
                    }
                }
                else if (args[i] == "--mappings")
                {
                    if (++i == args.Length)
                    {
                        throw new ArgumentException("--mappings requires a JSON file");
                    }
                    mappings = Path.GetFullPath(args[i], Path.GetFullPath(args[0]));
                }
                else if (args[i].StartsWith("--", StringComparison.Ordinal))
                {
                    throw new ArgumentException("Unknown or incomplete option: " + args[i]);
                }
                else
                {
                    projects.Add(args[i]);
                }
            }
            if ((qualificationDirectory is not null && !resolveReferences) || (qualificationUrl is not null && qualificationDirectory is null))
            {
                throw new ArgumentException("Qualification caching requires --resolve-references and --qualification-cache");
            }
            var root = WorkspaceView.PhysicalPath(args[0]);
            if (qualificationDirectory is not null && (QualificationInputs.Overlaps(root, qualificationDirectory) ||
                QualificationInputs.Overlaps(Path.GetDirectoryName(Path.GetDirectoryName(sdk))!, qualificationDirectory) || OperatingSystem.IsWindows()))
            {
                throw new ArgumentException("Qualification cache requires a separate directory on Linux");
            }
            if (qualificationDirectory is not null && !QualificationSandbox.Inside)
            {
                return QualificationSandbox.Run(root, sdk, projects.ToArray(), check, configuration, framework,
                    packageInputs.ToArray(), mappings, inputs, runfiles, new QualificationOptions(qualificationDirectory, qualificationUrl));
            }
            using var view = SyncProfile.Run("producer-bindings", () => WorkspaceView.Create(root, inputs, runfiles));
            if (view.HasIncompleteGraphBindings)
            {
                throw new InvalidDataException("Sync requires complete tool layouts in msbuild_sync bindings");
            }
            GraphGenerator.Run(view.Root, sdk, projects.ToArray(), check, root, configuration, framework, view, packageBuild, packageInputs.ToArray(), new GraphMappings(mappings), resolveReferences,
                qualificationDirectory is null ? null : new QualificationOptions(qualificationDirectory, qualificationUrl),
                QualificationSandbox.Inside ? QualificationSandbox.Base + "/output" : null);
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.Message);
            return 1;
        }
    }
}
