using System.Text.Json;

namespace RulesMSBuild.GraphBuild;

internal sealed record EngineRequest(string Target, bool ProfileBuild, int EvaluationCacheMb);
internal sealed record EngineReply(int ExitCode, string Output, bool Restart = false, bool Retire = false,
    long ManagedBytes = 0, long ResidentBytes = 0);

// The protocol belongs to the broker, not Bazel. This process remains inside
// one private stable-path sandbox; the broker replaces inputs only while idle.
internal static class GraphEngine
{
    internal static async Task<int> Run(string[] args, GraphRunOptions options)
    {
        if (args.Length != 4 || options.Prepared is null || !options.ReadOnlyPackages)
        {
            throw new InvalidDataException("Retained evaluation requires a prepared read-only Linux graph sandbox");
        }
        var contract = JsonSerializer.Deserialize<GraphContract>(File.ReadAllText(args[1])) ?? throw new InvalidDataException("Missing engine contract");
        var sdk = Environment.GetEnvironmentVariable("DOTNET_ROOT") ?? throw new InvalidDataException("Missing engine SDK");
        var selected = Path.Combine(sdk, "sdk", contract.SdkVersion);
        MSBuildContext.Bind(selected);
        Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", Path.Combine(selected, "MSBuild.dll"));
        Environment.SetEnvironmentVariable("MSBuildSDKsPath", Path.Combine(selected, "Sdks"));
        Environment.SetEnvironmentVariable("DOTNET_HOST_PATH", Path.Combine(sdk, "dotnet"));
        Environment.SetEnvironmentVariable("NUGET_PACKAGES", Path.Combine(args[0], ".nuget"));
        var protocol = Console.Out;
        var errors = Console.Error;
        using var evaluation = new EvaluationSession();
        while (await Console.In.ReadLineAsync() is { } line)
        {
            using var output = new StringWriter(System.Globalization.CultureInfo.InvariantCulture);
            Console.SetOut(output);
            Console.SetError(output);
            EngineReply reply;
            try
            {
                var request = JsonSerializer.Deserialize<EngineRequest>(line) ?? throw new InvalidDataException("Missing engine request");
                ClearScratch();
                var code = await GraphRunner.Run(["action", args[0], args[1], args[2], args[3], request.Target],
                    options with
                    {
                        Profile = request.ProfileBuild
                    }, evaluation);
                var retire = evaluation.Retire(request.EvaluationCacheMb, out var heap, out var resident);
                reply = new(code, output.ToString(), Retire: retire || code != 0, ManagedBytes: heap, ResidentBytes: resident);
            }
            catch (EvaluationRestartException)
            {
                reply = new(0, "", Restart: true);
            }
            catch (Exception error)
            {
                reply = new(1, output + error.ToString(), Retire: true);
            }
            finally
            {
                Console.SetOut(protocol);
                Console.SetError(errors);
            }
            await protocol.WriteLineAsync(JsonSerializer.Serialize(reply));
            await protocol.FlushAsync();
            if (reply.Restart || reply.Retire)
            {
                return reply.ExitCode;
            }
        }
        return 0;
    }
    private static void ClearScratch()
    {
        foreach (var directory in new[] { Environment.GetEnvironmentVariable("HOME")!, Path.GetTempPath() })
        {
            foreach (var path in Directory.EnumerateFileSystemEntries(directory))
            {
                if (Path.GetFileName(path).StartsWith("dotnet-diagnostic-" + Environment.ProcessId + "-", StringComparison.Ordinal))
                {
                    continue;
                }
                if (Directory.Exists(path) && !File.GetAttributes(path).HasFlag(FileAttributes.ReparsePoint))
                {
                    Directory.Delete(path, recursive: true);
                }
                else
                {
                    File.Delete(path);
                }
            }
        }
        Directory.CreateDirectory(Path.Combine(Environment.GetEnvironmentVariable("HOME")!, ".local", "share"));
    }

}
