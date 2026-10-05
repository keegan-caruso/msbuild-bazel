namespace RulesMSBuild.GraphBuild;

internal sealed record GraphRunOptions(string? RemoteUrl, string? BearerToken, string? LocalState,
    string? Prepared, bool ReadOnlyPackages, bool Profile, bool EvaluationProfile, string CopyMode)
{
    internal static GraphRunOptions Read()
    {
        string? Take(string name)
        {
            var value = Environment.GetEnvironmentVariable(name);
            Environment.SetEnvironmentVariable(name, null);
            return value;
        }
        var result = new GraphRunOptions(Take("RULES_MSBUILD_PROJECT_CACHE_URL"), Take("RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN"),
            Take("RULES_MSBUILD_GRAPH_LOCAL_STATE"), Take("RULES_MSBUILD_GRAPH_PREPARED_RESTORE"),
            Take("RULES_MSBUILD_GRAPH_READONLY_PACKAGES") == "1", Take("RULES_MSBUILD_GRAPH_PROFILE") == "1",
            Take("RULES_MSBUILD_GRAPH_EVALUATION_PROFILE") == "1", Take("RULES_MSBUILD_GRAPH_COPY_MODE") ?? "copy");
        if (result.CopyMode is not ("copy" or "clone"))
        {
            throw new InvalidDataException("RULES_MSBUILD_GRAPH_COPY_MODE must be copy or clone");
        }
        return result;
    }
}
