internal sealed record CachedItem(string Spec, Dictionary<string, string> Metadata);
internal sealed record Results(string Project, string Key, Dictionary<string, CachedItem[]> Targets, string? Inputs = null, string? Toolchain = null);
