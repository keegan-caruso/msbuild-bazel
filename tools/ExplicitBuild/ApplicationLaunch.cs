using System.Diagnostics;
using static Program;

internal static class ApplicationLaunch
{
    internal static int Run(Launch request, string[] args)
    {
        if (request.Test)
        {
            TestExecution.Validate(request.TestOptions ?? new());
        }

        var root = Environment.GetEnvironmentVariable("RULES_MSBUILD_RUNFILES") ?? throw new InvalidDataException("Missing runfiles root");
        var temporary = Path.Combine(Environment.GetEnvironmentVariable("TEST_TMPDIR") ?? Path.GetTempPath(), "msbuild-run-" + Guid.NewGuid().ToString("N"));
        var runtimeDirectory = request.Test && request.TestOptions?.WorkingDirectory is { } workingDirectory
            ? Path.Combine(temporary, Safe(workingDirectory)) : temporary;
        Directory.CreateDirectory(runtimeDirectory);
        try
        {
            var entryPackages = RuntimePackages.Read(Path.Combine(root, Safe(request.Entry)));
            var framework = RuntimePackages.FrameworkFiles(Path.Combine(root, Safe(request.Entry)));
            var packageInputs = (request.Packages ?? []).Select(p => p with { Directory = Path.Combine(root, Safe(p.Directory)) }).ToArray();
            foreach (var directory in request.Dependencies.Prepend(request.Entry))
            {
                var input = Path.Combine(root, Safe(directory));
                var packages = RuntimePackages.Read(input);
                foreach (var file in RuntimePackages.Files(input, packageInputs))
                {
                    var relative = file.Path;
                    if (directory != request.Entry && entryPackages.TryGetValue(relative, out var selected) && packages.TryGetValue(relative, out var inherited) && selected.Equals(inherited, StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    if (directory != request.Entry && packages.ContainsKey(relative) && RuntimePackages.SuppliedByFramework(file, framework))
                    {
                        continue;
                    }
                    Copy(file.Source, Path.Combine(runtimeDirectory, relative));
                }
            }
            foreach (var file in request.Data)
            {
                Copy(Path.Combine(root, Safe(file.Source)), Path.Combine(temporary, Safe(file.Path)));
            }

            var hostRoot = request.RuntimeHost is null ? Path.GetDirectoryName(Environment.ProcessPath!)! : Path.Combine(root, Safe(request.RuntimeHost.Directory));
            var host = request.RuntimeHost is null ? Environment.ProcessPath! : Path.Combine(hostRoot, Safe(request.RuntimeHost.EntryPoint));
            if (!File.Exists(host))
            {
                throw new InvalidDataException("Missing declared runtime host: " + host);
            }

            var mode = request.RuntimeHost?.LaunchMode ?? "dotnet";
            if (mode is not ("dotnet" or "corerun"))
            {
                throw new InvalidDataException("Unsupported runtime launch mode: " + mode);
            }
            if (mode == "corerun" && request.TestOptions?.Protocol == "vstest")
            {
                throw new InvalidDataException("VSTest requires a dotnet runtime host");
            }

            var start = new ProcessStartInfo(host) { WorkingDirectory = runtimeDirectory };
            foreach (var (name, value) in request.RuntimeHost?.Environment ?? [])
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

            if (request.Test)
            {
                return TestExecution.Run(start, request.TestOptions ?? new(), root, temporary);
            }

            using var process = Process.Start(start)!;
            using var interrupt = System.Runtime.InteropServices.PosixSignalRegistration.Create(System.Runtime.InteropServices.PosixSignal.SIGTERM, context => { context.Cancel = true; if (!process.HasExited) { process.Kill(true); } });
            process.WaitForExit();
            return process.ExitCode;
        }
        finally { Directory.Delete(temporary, true); }
    }
}
