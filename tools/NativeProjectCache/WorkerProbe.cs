using System.Collections;
using System.Diagnostics;
using System.Text.Json;

// Sequential process-reuse experiment. Not a sandbox or a Bazel worker contract.
internal static class WorkerProbe
{
    private sealed record Request(string RequestPath, string WorkingDirectory);
    internal static async Task<int> Run()
    {
        Program.ReuseEntryProcess = true;
        var output = Console.Out;
        var error = Console.Error;
        var directory = Environment.CurrentDirectory;
        try
        {
            while (await Console.In.ReadLineAsync() is { } line)
            {
                var request = JsonSerializer.Deserialize<Request>(line)!;
                using var log = new StringWriter();
                int code;
                try
                {
                    Console.SetOut(log); Console.SetError(log);
                    Environment.CurrentDirectory = request.WorkingDirectory;
                    code = await Program.Main(["--portable-request", request.RequestPath]);
                }
                finally
                {
                    Console.SetOut(output); Console.SetError(error);
                    Environment.CurrentDirectory = directory;
                }
                await output.WriteLineAsync(JsonSerializer.Serialize(new { exitCode = code, output = log.ToString() }));
                await output.FlushAsync();
            }
            return 0;
        }
        finally { Program.ReuseEntryProcess = false; }
    }

    internal static (int Code, string Log) Build(ProcessStartInfo start, string session)
    {
        var prior = Environment.GetEnvironmentVariables().Cast<DictionaryEntry>()
            .ToDictionary(pair => (string)pair.Key, pair => (string?)pair.Value);
        var directory = Environment.CurrentDirectory;
        var output = Console.Out; var error = Console.Error;
        using var log = new StringWriter();
        try
        {
            foreach (var key in prior.Keys) Environment.SetEnvironmentVariable(key, null);
            foreach (var (key, value) in start.Environment) Environment.SetEnvironmentVariable(key, value);
            var engine = Path.Combine(Path.GetDirectoryName(Environment.ProcessPath!)!, "sdk/10.0.400");
            Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", Path.Combine(engine, "MSBuild.dll"));
            Environment.SetEnvironmentVariable("MSBuildSDKsPath", Path.Combine(engine, "Sdks"));
            Environment.CurrentDirectory = start.WorkingDirectory;
            Console.SetOut(log); Console.SetError(log);
            return (EntryBuild.Run(session), log.ToString());
        }
        finally
        {
            Console.SetOut(output); Console.SetError(error);
            Environment.CurrentDirectory = directory;
            foreach (var key in Environment.GetEnvironmentVariables().Keys.Cast<string>().ToArray()) Environment.SetEnvironmentVariable(key, null);
            foreach (var (key, value) in prior) Environment.SetEnvironmentVariable(key, value);
        }
    }
}
