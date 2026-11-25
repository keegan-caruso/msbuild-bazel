using System.Diagnostics;
using RulesMSBuild;
using static Program;

internal static class TestProtocolLaunch
{
    internal static int Run(TestProtocolRequest request, string[] args)
    {
        TestExecution.Validate(request.TestOptions);

        var root = Environment.GetEnvironmentVariable("RULES_MSBUILD_RUNFILES") ?? throw new InvalidDataException("Missing runfiles root");
        var runfiles = new Runfiles(root);
        var temporary = Path.Combine(Environment.GetEnvironmentVariable("TEST_TMPDIR") ?? Path.GetTempPath(), "msbuild-run-" + Guid.NewGuid().ToString("N"));
        var runtimeDirectory = request.TestOptions.WorkingDirectory is { } workingDirectory
            ? Path.Combine(temporary, Safe(workingDirectory)) : temporary;
        Directory.CreateDirectory(runtimeDirectory);
        try
        {
            var input = runfiles.Resolve(Safe(request.Entry));
            // Bazel test runfiles expand tree artifacts into file symlinks.
            // This directory is the selected declared graph output, not a host tree.
            foreach (var file in Directory.EnumerateFiles(input, "*", SearchOption.AllDirectories))
            {
                Copy(file, Path.Combine(runtimeDirectory, Safe(RelativePathComponents.LogicalRelative(input, file))));
            }
            foreach (var file in request.Data)
            {
                Copy(runfiles.Resolve(Safe(file.Source)), Path.Combine(temporary, Safe(file.Path)));
            }

            var runtimeHost = request.RuntimeHost ?? throw new InvalidDataException("Missing declared runtime host");
            var hostRoot = runfiles.Resolve(Safe(runtimeHost.Directory));
            var host = Path.Combine(hostRoot, Safe(runtimeHost.EntryPoint));
            if (!File.Exists(host))
            {
                throw new InvalidDataException("Missing declared runtime host: " + host);
            }

            var mode = runtimeHost.LaunchMode;
            if (mode is not ("dotnet" or "corerun"))
            {
                throw new InvalidDataException("Unsupported runtime launch mode: " + mode);
            }
            if (mode == "corerun" && request.TestOptions.Protocol == "vstest")
            {
                throw new InvalidDataException("VSTest requires a dotnet runtime host");
            }

            var start = new ProcessStartInfo(host) { WorkingDirectory = runtimeDirectory };
            foreach (var (name, value) in runtimeHost.Environment ?? [])
            {
                start.Environment[name] = value;
            }
            start.Environment.Remove("CORE_ROOT");
            if (mode == "corerun")
            {
                start.Environment["CORE_ROOT"] = hostRoot;
            }
            start.Environment["DOTNET_ROOT"] = hostRoot;
            start.Environment["DOTNET_HOST_PATH"] = host;
            foreach (var architecture in new[] { "X64", "X86", "ARM", "ARM64" })
            {
                start.Environment["DOTNET_ROOT_" + architecture] = hostRoot;
            }

            start.Environment["DOTNET_MULTILEVEL_LOOKUP"] = "0";
            start.ArgumentList.Add(Path.Combine(runtimeDirectory, Safe(request.Assembly) + ".dll"));
            foreach (var arg in args)
            {
                start.ArgumentList.Add(arg);
            }

            return TestExecution.Run(start, request.TestOptions, runfiles, temporary);
        }
        finally { Directory.Delete(temporary, true); }
    }
}
