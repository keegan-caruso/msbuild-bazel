using System.Diagnostics;

namespace RulesMSBuild.GraphBuild;

// Fixed bind roots belong to the worker lease. Authored inputs and owned outputs
// are replaced each request; only pristine evaluation and cache artifacts persist.
internal sealed class WorkerEngine(string root) : IDisposable
{
    private RetainedGraphProcess? process;
    private string? preparation;
    private int budget;
    internal string Output { get; } = Path.Combine(root, "engine-output");
    private string Control { get; } = Path.Combine(root, "engine-control");
    private string Scratch { get; } = Path.Combine(root, "engine-scratch");
    internal int Generation
    {
        get; private set;
    }
    internal EngineReply? LastReply
    {
        get; private set;
    }

    internal string Prepare(string contract, string prepared)
    {
        if (preparation != prepared)
        {
            Stop();
            preparation = prepared;
        }
        Directory.CreateDirectory(Path.Combine(Output, "workspace", ".nuget"));
        Directory.CreateDirectory(Control);
        Directory.CreateDirectory(Scratch);
        var destination = Path.Combine(Control, "contract.json");
        File.Copy(contract, destination, overwrite: true);
        return destination;
    }

    internal async Task<EngineReply> Run(string sandbox, string sdk, string runner, string contract, string prepared, string cache, string target, bool profile, int megabytes)
    {
        if (budget != megabytes)
        {
            Stop();
            budget = megabytes;
        }
        for (var attempt = 0; attempt < 2; attempt++)
        {
            if (process is null)
            {
                var start = new ProcessStartInfo("/bin/bash");
                foreach (var argument in new[] { sandbox, sdk, runner, Output, contract, Scratch, target, "engine", prepared, cache, "1", "0" })
                {
                    start.ArgumentList.Add(argument);
                }
                process = new(start);
                Generation++;
            }
            var reply = await process.Run(new(target, profile, megabytes));
            LastReply = reply;
            if (reply.Restart)
            {
                Stop();
                continue;
            }
            if (reply.Retire || reply.ExitCode != 0)
            {
                Stop();
            }
            return reply;
        }
        throw new InvalidDataException("Evaluation context changed during engine restart");
    }

    internal void Stop()
    {
        process?.Dispose();
        process = null;
    }

    internal void ClearWorkspace()
    {
        var workspace = Path.Combine(Output, "workspace");
        if (Directory.Exists(workspace))
        {
            foreach (var path in Directory.EnumerateFileSystemEntries(workspace))
            {
                if (Path.GetFileName(path) == ".nuget")
                {
                    continue; // Preserve the mount point inode, not package contents.
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
        foreach (var name in new[] { "report.json", "report.binlog" })
        {
            File.Delete(Path.Combine(Output, name));
        }
    }

    public void Dispose() => Stop();
}
