namespace RulesMSBuild.ProjectSync;

internal static class Program
{
    public static int Main(string[] args)
    {
        try
        {
            if (args.Length < 3)
            {
                throw new ArgumentException("ProjectSync <workspace> <sdk-directory> <project.csproj>... [--check]");
            }
            var sdk = Path.GetFullPath(args[1]);
            if (!File.Exists(Path.Combine(sdk, "MSBuild.dll")))
            {
                throw new ArgumentException("sdk-directory must contain MSBuild.dll");
            }
            System.Runtime.Loader.AssemblyLoadContext.Default.Resolving += (context, name) => File.Exists(Path.Combine(sdk, name.Name + ".dll")) ? context.LoadFromAssemblyPath(Path.Combine(sdk, name.Name + ".dll")) : null;
            Environment.SetEnvironmentVariable("MSBuildEnableWorkloadResolver", "false");
            Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", Path.Combine(sdk, "MSBuild.dll"));
            Environment.SetEnvironmentVariable("MSBuildSDKsPath", Path.Combine(sdk, "Sdks"));
            Generator.Run(Path.GetFullPath(args[0]), sdk, args.Skip(2).Where(a => a != "--check").ToArray(), args.Contains("--check"));
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.Message);
            return 1;
        }
    }
}
