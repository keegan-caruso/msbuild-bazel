using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Build.Graph;

namespace RulesMSBuild.GraphBuild;

internal sealed record LocalStateManifest(int Version, string Root, string Identity, string[] Directories, string[] Files, bool Complete);

// An explicit, owned workspace experiment. Cache misses still start with empty
// project outputs; only verified cache hits may retain their existing files.
internal sealed class LocalGraphState : IDisposable
{
    private readonly FileStream lease;
    private readonly FileStream workspaceLease;
    private readonly string manifestPath;
    private readonly ContractFiles files;
    private readonly LocalStateManifest? previous;
    private LocalStateManifest current;
    internal bool Reusable
    {
        get; private set;
    }

    internal LocalGraphState(string directory, GraphContract contract, ContractFiles files)
    {
        if (!OperatingSystem.IsLinux())
        {
            throw new InvalidDataException("Retained graph state currently requires Linux");
        }
        contract = CompileGlobInputs.Expand(contract, files);
        this.files = files;
        directory = Path.GetFullPath(directory);
        if (directory == files.Root || directory.StartsWith(files.Root + "/", StringComparison.Ordinal))
        {
            throw new InvalidDataException("Graph state metadata must be outside the workspace");
        }
        Directory.CreateDirectory(directory);
        manifestPath = Path.Combine(directory, "state.json");
        var lockPath = Path.Combine(directory, "state.lock");
        if (new DirectoryInfo(directory).LinkTarget is not null || new FileInfo(manifestPath).LinkTarget is not null || new FileInfo(lockPath).LinkTarget is not null)
        {
            throw new InvalidDataException("Graph state metadata must not be linked");
        }
        workspaceLease = LockWorkspace(files.Root);
        try
        {
            lease = new FileStream(lockPath, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        }
        catch
        {
            workspaceLease.Dispose();
            throw;
        }
        try
        {
            previous = File.Exists(manifestPath) ? JsonSerializer.Deserialize<LocalStateManifest>(File.ReadAllText(manifestPath)) : null;
            if (previous is not null && (previous.Version != 1 || previous.Root != files.Root))
            {
                throw new InvalidDataException("Graph state belongs to a different workspace or version");
            }
            var declarations = contract.Projects.Values;
            var directories = declarations.SelectMany(project => project.OutputDirectories.Concat((project.Configurations ?? []).SelectMany(item => item.OutputDirectories)))
                .Distinct().Order(StringComparer.Ordinal).ToArray();
            var outputs = declarations.SelectMany(project => (project.OutputFiles ?? []).Concat((project.Configurations ?? []).SelectMany(item => item.OutputFiles ?? [])))
                .Distinct().Order(StringComparer.Ordinal).ToArray();
            current = new(1, files.Root, "", directories, outputs, false);
            var inputs = contract.SharedInputs.Concat(declarations.SelectMany(project => project.Inputs.Concat((project.Configurations ?? []).SelectMany(item => item.Inputs))))
                .Concat(contract.Restore?.Inputs ?? []).Concat(contract.InputDirectories ?? []).Concat(contract.Projects.Keys)
                .Concat((contract.DefinitionDigests ?? []).Keys).Select(files.Resolve).ToArray();
            foreach (var state in previous is null ? new[] { current } : new[] { previous, current })
            {
                foreach (var relative in state.Directories.Concat(state.Files))
                {
                    var path = files.Resolve(relative);
                    if (relative.Split('/')[0] is ".nuget" or ".package-source" or ".graph-tools" ||
                        inputs.Any(input => input == path || input.StartsWith(path + "/", StringComparison.Ordinal)))
                    {
                        throw new InvalidDataException("Retained state overlaps declared inputs: " + relative);
                    }
                }
            }
            if (previous is null && (directories.Any(path => Directory.Exists(files.Resolve(path)) && Directory.EnumerateFileSystemEntries(files.Resolve(path)).Any()) || outputs.Any(path => Path.Exists(files.Resolve(path)))))
            {
                throw new InvalidDataException("New graph state requires empty owned outputs");
            }
            if (previous is not null && (!previous.Complete || !previous.Directories.SequenceEqual(directories) || !previous.Files.SequenceEqual(outputs)))
            {
                Clear(previous);
                Clear(current);
            }
            // A failed Restore, evaluation or build leaves an incomplete marker.
            Write(current);
        }
        catch
        {
            lease.Dispose();
            workspaceLease.Dispose();
            throw;
        }
    }

    internal void Prepare(GraphInputs inputs, string target)
    {
        var identity = ContractFiles.Hash(new[] { inputs.SdkDigest, ContractFiles.Digest(typeof(LocalGraphState).Assembly.Location), target }
            .Concat(inputs.Graph.ProjectNodes.Select(node => GraphInputs.Key(node.ProjectInstance)).Order(StringComparer.Ordinal)));
        Reusable = previous is { Complete: true } && previous.Identity == identity &&
            previous.Directories.SequenceEqual(current.Directories) && previous.Files.SequenceEqual(current.Files);
        if (!Reusable)
        {
            Clear(current);
        }
        current = current with
        {
            Identity = identity
        };
        Write(current);
    }

    internal void ResetProject(GraphInputs inputs, ProjectGraphNode node)
    {
        foreach (var directory in inputs.OutputDirectories(node))
        {
            if (Directory.Exists(directory))
            {
                Directory.Delete(directory, recursive: true);
            }
        }
        foreach (var path in inputs.DeclaredOutputFiles(node))
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
    }

    internal void RemoveObsoleteOutputs(GraphInputs inputs, ProjectGraphNode node, IEnumerable<string> expected)
    {
        var keep = expected.ToHashSet(StringComparer.Ordinal);
        var existing = inputs.OutputDirectories(node).Where(Directory.Exists)
            .SelectMany(directory => Directory.EnumerateFiles(directory, "*", SearchOption.AllDirectories))
            .Concat(inputs.DeclaredOutputFiles(node).Where(File.Exists));
        foreach (var path in existing.ToArray())
        {
            var relative = Path.GetRelativePath(files.Root, path);
            files.Resolve(relative);
            if (!keep.Contains(relative))
            {
                File.Delete(path);
            }
        }
    }

    internal static bool Matches(string path, string digest)
    {
        // Never retain a hard-linked output: a later write could mutate a producer
        // or cache inode. statx has a fixed ABI on the qualified Linux platforms.
        return OperatingSystem.IsLinux() && File.Exists(path) && Status(-100, path, 0x100, 0x4, out var status) == 0 &&
            (status.Mask & 0x4) != 0 && status.Links == 1 && ContractFiles.Digest(path) == digest;
    }

    internal void Complete() => Write(current with { Complete = true });

    private void Clear(LocalStateManifest state)
    {
        foreach (var relative in state.Directories)
        {
            var path = files.Resolve(relative);
            if (Directory.Exists(path))
            {
                Directory.Delete(path, recursive: true);
            }
        }
        foreach (var relative in state.Files)
        {
            var path = files.Resolve(relative);
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
    }

    private void Write(LocalStateManifest state)
    {
        var temporary = manifestPath + ".pending-" + Guid.NewGuid().ToString("N");
        try
        {
            File.WriteAllText(temporary, JsonSerializer.Serialize(state));
            File.Move(temporary, manifestPath, overwrite: true);
        }
        finally
        {
            File.Delete(temporary);
        }
    }

    public void Dispose()
    {
        lease.Dispose();
        workspaceLease.Dispose();
    }

    private static FileStream LockWorkspace(string root)
    {
        if (!OperatingSystem.IsLinux())
        {
            throw new PlatformNotSupportedException();
        }
        var user = EffectiveUserId();
        var directory = Path.Combine(Path.GetTempPath(), "rules-msbuild-graph-state-" + user.ToString(System.Globalization.CultureInfo.InvariantCulture));
        const UnixFileMode mode = UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute;
        Directory.CreateDirectory(directory, mode);
        if (Status(-100, directory, 0x100, 0x8, out var status) != 0 || (status.Mask & 0x8) == 0 || status.UserId != user ||
            new DirectoryInfo(directory).LinkTarget is not null || File.GetUnixFileMode(directory) != mode)
        {
            throw new InvalidDataException("Graph workspace leases require a private owned directory");
        }
        var path = Path.Combine(directory, ContractFiles.Hash([root]) + ".state.lock");
        if (new FileInfo(path).LinkTarget is not null)
        {
            throw new InvalidDataException("Graph workspace lease must not be linked");
        }
        return new FileStream(path, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
    }

    [DllImport("libc", EntryPoint = "geteuid")]
    private static extern uint EffectiveUserId();

    [StructLayout(LayoutKind.Explicit, Size = 256)]
    private struct FileStatus
    {
        [FieldOffset(0)] public uint Mask;
        [FieldOffset(16)] public uint Links;
        [FieldOffset(20)] public uint UserId;
    }
    [DllImport("libc", EntryPoint = "statx", SetLastError = true)]
    private static extern int Status(int directory, string path, int flags, uint mask, out FileStatus status);
}
