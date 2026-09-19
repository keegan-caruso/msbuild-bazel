using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

// A reviewed, pinned application profile. It does not grant arbitrary project
// XML, package build logic or SDK imports permission to cross discovery's guard.
internal sealed class OrchardProfile
{
    private readonly JsonNode? policy;
    private readonly string workspace;
    private readonly string? sdk;
    public OrchardProfile(string root, string workspace, string? sdk = null)
    {
        this.workspace = workspace; this.sdk = sdk;
        var candidate = Json.Read(Path.Combine(root, "tools/orchard-discovery-policy.json"));
        if (candidate["schemaVersion"]?.GetValue<int>() != 1) throw new InvalidDataException("Invalid Orchard discovery policy");
        if (candidate["anchors"]!.AsObject().All(pair =>
            File.Exists(Path.Combine(workspace, Host.Safe(pair.Key))) &&
            Json.Sha(File.ReadAllBytes(Path.Combine(workspace, pair.Key))) == pair.Value!.GetValue<string>())) policy = candidate;
    }
    public bool OwnsImport(JsonNode node, string relative)
    {
        var path = Path.Combine(workspace, Host.Safe(relative));
        return policy is not null && node.Array("inputs").Any(input => input!.String("kind") == "import" && input.String("path") == "workspace/" + relative) &&
            File.Exists(path) && Accept(path, FileTree.HashRegular(path).Digest);
    }
    public IEnumerable<string> Packages => (policy?["packages"] as JsonArray ?? []).Select(value => value!.GetValue<string>());
    public bool Accept(string path, string hash)
    {
        if (policy is null) return false;
        var logical = Host.Within(path, Path.Combine(workspace, ".nuget/packages")) ? "packages/" + Path.GetRelativePath(Path.Combine(workspace, ".nuget/packages"), path)
            : Host.Within(path, workspace) ? "workspace/" + Path.GetRelativePath(workspace, path)
            : sdk is not null && Host.Within(path, sdk) ? "dotnet/" + Path.GetRelativePath(sdk, path)
            : path.StartsWith("/nix/store/", StringComparison.Ordinal) ? "nix/" + path["/nix/store/".Length..] : "";
        return policy["imports"]?[logical]?.GetValue<string>() == hash;
    }
}
