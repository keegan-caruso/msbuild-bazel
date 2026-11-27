using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace RulesMSBuild.GraphBuild;

internal static class WindowsSync
{
    internal static Task<int> Run(string[] args)
    {
        if (!OperatingSystem.IsWindows() || RuntimeInformation.OSArchitecture != Architecture.X64 ||
            RuntimeInformation.ProcessArchitecture != Architecture.X64)
        {
            throw new PlatformNotSupportedException("Windows sync isolation requires native Windows x64");
        }
        if (args.Length < 8 || !RelativePathComponents.IsSafeRelative(args[3], true) || args[3].Contains('/'))
        {
            throw new ArgumentException("Expected SDK, ProjectSync, staged input directory, SDK version, output, manifest, mappings or -, and projects");
        }
        return Evaluate(args);
    }

    [SupportedOSPlatform("windows")]
    private static async Task<int> Evaluate(string[] args)
    {
        using var lease = new WindowsSandboxLease();
        WindowsStorage.Integrity(lease.Action, false);
        WindowsStorage.Copy(args[0], Path.Combine(lease.Action, "sdk"));
        WindowsStorage.Copy(args[1], Path.Combine(lease.Action, "runner"));
        WindowsStorage.Copy(args[2], Path.Combine(lease.Action, "inputs"));
        File.Copy(args[5], Path.Combine(lease.Action, "manifest.json"));
        if (args[6] != "-")
        {
            File.Copy(args[6], Path.Combine(lease.Action, "mappings.json"));
        }
        var output = Directory.CreateDirectory(Path.Combine(lease.Action, "output")).FullName;
        var environment = WindowsExecution.Prepare(lease);
        var root = lease.Root;
        var workspace = root + @"inputs\workspace";
        var command = new List<string> { "exec", root + @"runner\ProjectSync.dll", "windows-prepared", root + "output", root + "scratch", workspace,
            root + @"sdk\sdk\" + args[3], "--inputs", root + "manifest.json", "--runfiles", root + @"inputs\runfiles" };
        if (args[6] != "-")
        {
            command.AddRange(["--mappings", root + "mappings.json"]);
        }
        command.AddRange(args[7..]);
        var result = await WindowsExecution.Run(lease, command, workspace, environment);
        if (result == 0)
        {
            // The job is empty. Validate the contents before returning the two
            // generated declarations to the ordinary prepared-sync publisher.
            WindowsStorage.CopySyncOutputs(output, args[4]);
        }
        return result;
    }
}
