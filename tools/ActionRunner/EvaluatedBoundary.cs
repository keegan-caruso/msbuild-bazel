using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Text.Json;

namespace ActionRunner;

// Retain SDK/package runtime contracts in compilation identities. Only known
// project DLL/PDB/XML bytes are deferred to current-result runtime composition.
internal static class EvaluatedBoundary
{
    internal static string Framework(string bundle)
    {
        using var results = JsonDocument.Parse(File.ReadAllText(Path.Combine(bundle, "results.json")));
        var framework = results.RootElement.TryGetProperty("targetFramework", out var value) ? value.GetString() : "net10.0";
        return framework is "net10.0" or "netstandard2.0" ? framework : throw new InvalidDataException("Unqualified bundle framework");
    }
    private static string Bin(string project, string framework) => Path.Combine(Path.GetDirectoryName(project)!, "bin/Release", framework);
    private static string Assembly(string project) => Path.GetFileNameWithoutExtension(project);
    private static string Reference(string project, string framework) => Path.Combine(Path.GetDirectoryName(project)!, "obj/Release", framework, "ref", Assembly(project) + ".dll");

    internal static bool CopiesProjectRuntime(string copyPolicy, IEnumerable<string> paths, ISet<string> runtimeNames) =>
        copyPolicy.Length != 0 && !copyPolicy.Equals("Never", StringComparison.OrdinalIgnoreCase) &&
        paths.Any(path => runtimeNames.Contains(Path.GetFileName(path.Replace('\\', '/'))));

    private static object? Canonical(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.Object => value.EnumerateObject().OrderBy(property => property.Name, StringComparer.Ordinal)
            .ToDictionary(property => property.Name, property => Canonical(property.Value)),
        JsonValueKind.Array => value.EnumerateArray().Select(Canonical).ToArray(),
        _ => value.Clone()
    };

    internal static string Identity(string bundle, string project, string[] closure, string[] dependencies, bool runtimeReferences = false, bool fullImplementation = false, Func<string, Artifact[]>? validate = null)
    {
        var artifacts = (validate ?? CompileBoundary.Validate)(bundle); var framework = Framework(bundle);
        if (fullImplementation)
        {
            using var fullResults = JsonDocument.Parse(File.ReadAllText(Path.Combine(bundle, "results.json")));
            var content = JsonSerializer.SerializeToUtf8Bytes(new
            {
                policy = "implementation-dependency-v1",
                framework,
                artifacts = artifacts.OrderBy(item => item.Path, StringComparer.Ordinal),
                targets = Canonical(fullResults.RootElement.GetProperty("targets")),
                dependencies
            });
            return Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(content));
        }
        if (!artifacts.Any(item => item.Path == Reference(project, framework)))
            throw new InvalidDataException("evaluated reference assembly missing");
        var implementations = closure.SelectMany(dependency => new[] { ".dll", ".pdb", ".xml" }
            .Select(extension => Path.Combine(Bin(project, framework), Assembly(dependency) + extension))).ToHashSet(StringComparer.Ordinal);
        // Do not classify a package asset as a project implementation merely
        // because their filenames collide. Such runtime selection needs its own
        // qualification rather than silently replacing the SDK's chosen asset.
        using var metadata = JsonDocument.Parse(File.ReadAllText(Path.Combine(bundle, "artifacts", Bin(project, framework), Assembly(project) + ".deps.json")));
        var libraries = metadata.RootElement.GetProperty("libraries");
        foreach (var target in metadata.RootElement.GetProperty("targets").EnumerateObject())
            foreach (var library in target.Value.EnumerateObject())
                if (libraries.GetProperty(library.Name).GetProperty("type").GetString() == "package" && library.Value.TryGetProperty("runtime", out var runtime))
                    foreach (var asset in runtime.EnumerateObject())
                        if (implementations.Contains(Path.Combine(Bin(project, framework), Path.GetFileName(asset.Name))))
                            throw new InvalidDataException("package and project runtime names collide");
        // Preserve membership, all reference bytes, SDK metadata, package assets
        // and replay target metadata. Propagate transitive compile contracts too.
        using var results = JsonDocument.Parse(File.ReadAllText(Path.Combine(bundle, "results.json")));
        var identity = JsonSerializer.SerializeToUtf8Bytes(new
        {
            artifacts = artifacts.OrderBy(item => item.Path, StringComparer.Ordinal)
                .Select(item => new { item.Path, Sha256 = implementations.Contains(item.Path) ? null : item.Sha256 }),
            runtimeReferences = runtimeReferences ? implementations.Where(path => path.EndsWith(".dll", StringComparison.Ordinal) && File.Exists(Path.Combine(bundle, "artifacts", path))).Order(StringComparer.Ordinal).Select(path =>
            {
                using var stream = File.OpenRead(Path.Combine(bundle, "artifacts", path)); using var pe = new PEReader(stream); var reader = pe.GetMetadataReader();
                return new
                {
                    path,
                    references = reader.AssemblyReferences.Select(handle =>
                    {
                        var reference = reader.GetAssemblyReference(handle);
                        return new { name = reader.GetString(reference.Name), version = reference.Version.ToString(), culture = reader.GetString(reference.Culture), key = Convert.ToHexString(reader.GetBlobBytes(reference.PublicKeyOrToken)), flags = (int)reference.Flags };
                    }).OrderBy(reference => reference.name, StringComparer.Ordinal).ToArray()
                };
            }).ToArray() : null,
            targets = Canonical(results.RootElement.GetProperty("targets")),
            dependencies
        });
        return Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(identity));
    }

    // A compile hit may carry historical copy-local implementations. Publish
    // current, valid runtime bytes so identical sources have identical seeds
    // regardless of which project happened to compile in this invocation.
    internal static bool RefreshBundle(string bundle, string project, Dictionary<string, string> dependencies, string output, Func<string, Artifact[]>? validate = null)
    {
        validate ??= CompileBoundary.Validate;
        var own = validate(bundle); var changed = false; var framework = Framework(bundle);
        foreach (var (dependency, producer) in dependencies)
        {
            var artifacts = validate(producer);
            foreach (var extension in new[] { ".dll", ".pdb", ".xml" })
            {
                var selected = own.SingleOrDefault(item => item.Path == Path.Combine(Bin(project, framework), Assembly(dependency) + extension));
                if (selected is null) continue;
                var current = artifacts.SingleOrDefault(item => item.Path == Path.Combine(Bin(dependency, Framework(producer)), Assembly(dependency) + extension))
                    ?? throw new InvalidDataException("Current runtime artifact missing during seed refresh");
                changed |= selected.Sha256 != current.Sha256;
            }
        }
        if (!changed) return false;
        Files.CopyTree(bundle, output);
        Files.NormalizeTree(output);
        Compose(bundle, project, dependencies, Path.Combine(output, "artifacts"), validate: validate);
        CompileBoundary.Seal(output);
        return true;
    }

    internal static void Compose(string bundle, string project, Dictionary<string, string> dependencies, string workspace, bool verifySelection = false, Func<string, Artifact[]>? validate = null)
    {
        validate ??= CompileBoundary.Validate;
        var own = validate(bundle); var framework = Framework(bundle);
        var replacements = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var (dependency, producer) in dependencies)
        {
            var artifacts = validate(producer);
            var assembly = Path.Combine(Bin(dependency, Framework(producer)), Assembly(dependency) + ".dll");
            if (!artifacts.Any(item => item.Path == assembly))
                throw new InvalidDataException("current project implementation missing");
            foreach (var extension in new[] { ".dll", ".pdb", ".xml" })
            {
                var destination = Path.Combine(Bin(project, framework), Assembly(dependency) + extension);
                // Preserve the SDK's selected copy-local membership and layout.
                var selected = own.SingleOrDefault(item => item.Path == destination);
                if (selected is null) continue;
                var source = Path.ChangeExtension(assembly, extension);
                var original = artifacts.SingleOrDefault(item => item.Path == source);
                if (original is null || !replacements.TryAdd(destination, Path.Combine(producer, "artifacts", source)))
                    throw new InvalidDataException("ambiguous or missing current runtime artifact");
                if (verifySelection && selected.Sha256 != original.Sha256)
                    throw new InvalidDataException("SDK output overrides a project runtime artifact");
            }
        }
        // Establish producer ownership on fresh compilation before caching it.
        // A later hit can then safely refresh historical copy-local bytes.
        if (verifySelection) return;
        // Validate every producer before writing. Composition never mutates a
        // sealed compilation cache bundle or synthesizes NuGet/SDK metadata.
        foreach (var (destination, source) in replacements)
            Files.CopyNormalized(source, Path.Combine(workspace, destination));
    }
}
