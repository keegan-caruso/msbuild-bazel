using System.Diagnostics;
using System.Text.Json;

internal static class DependencyReplayTests
{
    internal static void Run()
    {
        var directory = Directory.CreateTempSubdirectory("dependency-replay-");
        try
        {
            var path = Path.Combine(directory.FullName, "Dependency.csproj");
            var results = new Results("Dependency.csproj", new string('a', 64), new()
            {
                ["Recorded"] = [new CachedItem("${WORKSPACE}/literal%3Bitem", new() { ["Literal"] = "$(MustNotExpand)", ["List"] = "first%3Bsecond" })]
            });
            DependencyReplay.Write(path, results, directory.FullName);
            (int Exit, string Output) Execute(string target)
            {
                var start = new ProcessStartInfo(Environment.ProcessPath!) { RedirectStandardOutput = true, RedirectStandardError = true };
                foreach (var arg in new[] { "msbuild", path, "-t:" + target, "-getTargetResult:" + target, "-nologo", "-nodeReuse:false" }) start.ArgumentList.Add(arg);
                using var process = Process.Start(start)!;
                var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
                if (!process.WaitForExit(30000)) { process.Kill(true); throw new InvalidOperationException("Replay target test timed out"); }
                return (process.ExitCode, stdout.Result + stderr.Result);
            }
            var success = Execute("Recorded");
            if (success.Exit != 0) throw new InvalidOperationException(success.Output);
            using var parsed = JsonDocument.Parse(success.Output);
            var item = parsed.RootElement.GetProperty("TargetResults").GetProperty("Recorded").GetProperty("Items")[0];
            if (item.GetProperty("Identity").GetString() != directory.FullName + "/literal;item" ||
                item.GetProperty("Literal").GetString() != "$(MustNotExpand)" || item.GetProperty("List").GetString() != "first;second")
                throw new InvalidOperationException("Recorded target values changed during replay");
            var prepared = Path.Combine(directory.FullName, "prepared;$(Literal)@x.dll");
            DependencyReplay.Write(path, results, directory.FullName, value => value == "${WORKSPACE}/literal%3Bitem"
                ? DependencyReplay.EscapePath(prepared) : value.Replace("${WORKSPACE}", directory.FullName, StringComparison.Ordinal));
            var redirected = Execute("Recorded");
            using var redirectedResult = JsonDocument.Parse(redirected.Output);
            if (redirected.Exit != 0 || redirectedResult.RootElement.GetProperty("TargetResults").GetProperty("Recorded").GetProperty("Items")[0].GetProperty("Identity").GetString() != prepared ||
                DependencyReplay.UnescapePath(DependencyReplay.EscapePath(prepared)) != prepared)
                throw new InvalidOperationException("Prepared paths lost MSBuild escaping");
            var failure = Execute("UnrecordedDependencyTarget");
            if (failure.Exit == 0 || !failure.Output.Contains("MSB4057", StringComparison.Ordinal)) throw new InvalidOperationException("Unknown dependency target did not fail closed");
        }
        finally { Directory.Delete(directory.FullName, true); }
    }
}
