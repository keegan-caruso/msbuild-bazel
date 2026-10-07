using System.Collections.Concurrent;
using Microsoft.Build.Definition;
using Microsoft.Build.Evaluation;
using Microsoft.Build.Evaluation.Context;

namespace RulesMSBuild.GraphBuild;

// Pristine evaluation only. Every build receives a fresh full-state instance;
// BuildManager, tasks, outputs, byte verification and project snapshots stay per request.
internal sealed class EvaluationSession : IDisposable
{
    private readonly ConcurrentDictionary<string, Lazy<Project>> projects = new(StringComparer.Ordinal);
    private string? identity;
    private int loaded;
    private int reused;
    internal ProjectCollection Collection { get; } = new();
    internal EvaluationContext Context { get; } = EvaluationContext.Create(EvaluationContext.SharingPolicy.Shared);
    internal object Report => new { loaded, reused, configuredProjects = projects.Count };

    internal void Prepare(GraphContract contract, ContractFiles files, string sdkDigest, Dictionary<string, string> digests)
    {
        if (contract.Version is not (9 or 10 or 11) || contract.EvaluationReuseInputs is null)
        {
            throw new InvalidDataException("Evaluation reuse requires a version 9, 10 or 11 reviewed compiler-only input inventory");
        }
        var compilerOnly = contract.EvaluationReuseInputs.ToHashSet(StringComparer.Ordinal);
        if (compilerOnly.Count != contract.EvaluationReuseInputs.Length || compilerOnly.Any(path => !digests.ContainsKey(path) ||
            (contract.DefinitionDigests ?? []).ContainsKey(path) || contract.SharedInputs.Contains(path) ||
            (contract.Restore?.Inputs ?? []).Contains(path) || (contract.Restore?.Outputs ?? []).Contains(path)))
        {
            throw new InvalidDataException("Evaluation reuse inputs must be distinct declared compiler-only project files");
        }
        // All bytes were verified for this request. Only the explicit reviewed
        // inventory omits content from the evaluation identity, never from build keys.
        var membership = Directory.EnumerateFiles(files.Root, "*", SearchOption.AllDirectories).Select(path => Path.GetRelativePath(files.Root, path)).Order(StringComparer.Ordinal).ToArray();
        var records = new[] { sdkDigest, ContractFiles.TreeDigest(AppContext.BaseDirectory), System.Text.Json.JsonSerializer.Serialize(contract) }
            .Concat(digests.OrderBy(pair => pair.Key, StringComparer.Ordinal).Select(pair => pair.Key + ":" + (compilerOnly.Contains(pair.Key) ? "compiler-only" : pair.Value)))
            .Concat(membership.Select(path => "member:" + path))
            .Concat(membership.Except(digests.Keys, StringComparer.Ordinal).Select(path => "extra:" + path + ":" + ContractFiles.InputDigest(files.Resolve(path))))
            .Concat(Directory.EnumerateDirectories(files.Root, "*", SearchOption.AllDirectories).Select(path => Path.GetRelativePath(files.Root, path)).Order(StringComparer.Ordinal).Select(path => "directory:" + path))
            .Concat(digests.Keys.Where(path => !compilerOnly.Contains(path))
                .Order(StringComparer.Ordinal).Select(path => "definition-time:" + path + ":" + File.GetLastWriteTimeUtc(files.Resolve(path)).Ticks))
            .Concat(Directory.EnumerateFiles(files.Sdk, "*", SearchOption.AllDirectories).Where(path => path.EndsWith(".props", StringComparison.Ordinal) || path.EndsWith(".targets", StringComparison.Ordinal))
                .Order(StringComparer.Ordinal).Select(path => "sdk-time:" + path + ":" + File.GetLastWriteTimeUtc(path).Ticks))
            .Concat(Environment.GetEnvironmentVariables().Cast<System.Collections.DictionaryEntry>().OrderBy(pair => (string)pair.Key, StringComparer.Ordinal).Select(pair => pair.Key + "=" + pair.Value));
        var next = ContractFiles.Hash(records);
        if (identity is not null && identity != next)
        {
            // Restart also discards SDK resolvers, property-function assemblies,
            // file-system caches and other MSBuild process state beyond ProjectCollection.
            throw new EvaluationRestartException();
        }
        identity = next;
        loaded = 0;
        reused = 0;
    }

    internal Project Load(string path, Dictionary<string, string> globals, ProjectOptions options)
    {
        var key = path + "|" + ContractFiles.Hash(globals.OrderBy(pair => pair.Key, StringComparer.Ordinal).Select(pair => pair.Key + "=" + pair.Value));
        var pending = new Lazy<Project>(() =>
        {
            Interlocked.Increment(ref loaded);
            return Project.FromFile(path, options);
        });
        var selected = projects.GetOrAdd(key, pending);
        if (selected != pending)
        {
            Interlocked.Increment(ref reused);
        }
        return selected.Value;
    }

    // Bounds apply between requests. Collect only when needed to distinguish
    // transient build garbage from live evaluation state.
    internal bool Retire(int megabytes, out long managedBytes, out long residentBytes)
    {
        var heapLimit = (long)megabytes * 1024 * 1024;
        managedBytes = GC.GetTotalMemory(false);
        if (managedBytes > heapLimit)
        {
            managedBytes = GC.GetTotalMemory(true);
        }
        using var process = System.Diagnostics.Process.GetCurrentProcess();
        residentBytes = process.WorkingSet64;
        return projects.Count > 1024 || managedBytes > heapLimit || residentBytes > Math.Max(256L * 1024 * 1024, 3 * heapLimit);
    }

    public void Dispose() => Collection.Dispose();
}

internal sealed class EvaluationRestartException : Exception;
