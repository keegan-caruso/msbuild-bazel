using System.Reflection;
using System.Text.Json;
using Microsoft.Build.Execution;
using Microsoft.Build.Experimental.FileAccess;
using Microsoft.Build.ProjectCache;

// An observation-only plugin: every query is a miss, never a fabricated cache hit.
public sealed class CapabilityPlugin : ProjectCachePluginBase
{
    private int queries;
    private int finished;
    private int nodes;
    private int fileAccesses;
    private string? loadError;
    private string? oldApiType;

    public override Task BeginBuildAsync(CacheContext context, PluginLoggerBase logger, CancellationToken token)
    {
        nodes = context.Graph?.ProjectNodes.Count ?? 0;
        oldApiType = typeof(ProjectCachePluginBase).Assembly.GetType("Microsoft.Build.Experimental.ProjectCache.ProjectCachePluginBase")?.FullName;
        var upstream = Environment.GetEnvironmentVariable("MSBUILD_CACHE_PROBE_ASSEMBLY");
        if (upstream is not null)
        {
            try
            {
                var assembly = Assembly.LoadFrom(upstream);
                _ = assembly.GetTypes();
            }
            catch (Exception error)
            {
                loadError = error.ToString();
                if (error is ReflectionTypeLoadException types)
                    loadError += string.Join("\n", types.LoaderExceptions.Select(exception => exception?.ToString()));
            }
        }
        return Task.CompletedTask;
    }

    public override Task<CacheResult> GetCacheResultAsync(BuildRequestData request, PluginLoggerBase logger, CancellationToken token)
    {
        Interlocked.Increment(ref queries);
        return Task.FromResult(CacheResult.IndicateNonCacheHit(CacheResultType.CacheMiss));
    }

    public override Task HandleProjectFinishedAsync(FileAccessContext context, BuildResult result, PluginLoggerBase logger, CancellationToken token)
    {
        Interlocked.Increment(ref finished);
        return Task.CompletedTask;
    }

    public override void HandleFileAccess(FileAccessContext context, FileAccessData data) => Interlocked.Increment(ref fileAccesses);

    public override Task EndBuildAsync(PluginLoggerBase logger, CancellationToken token)
    {
        var output = Environment.GetEnvironmentVariable("MSBUILD_CACHE_PROBE_REPORT") ?? throw new InvalidOperationException("probe report path missing");
        File.WriteAllText(output, JsonSerializer.Serialize(new
        {
            graphNodes = nodes,
            cacheQueries = queries,
            projectFinished = finished,
            fileAccessReports = fileAccesses,
            cacheHits = 0,
            oldApiType,
            upstreamLoadError = loadError,
            engine = typeof(BuildManager).Assembly.FullName,
            callbacks = typeof(ProjectCachePluginBase).GetMethods().Where(method => method.DeclaringType == typeof(ProjectCachePluginBase)).Select(method => method.ToString()).ToArray()
        }, new JsonSerializerOptions { WriteIndented = true }));
        return Task.CompletedTask;
    }
}
