namespace ActionRunner;

internal static class NativeRuntimeInputs
{
    public static void Validate(ActionRequest request)
    {
        if (request.NativeManifest is null)
            return;
        var manifest = JsonFiles.Read<NativeManifest>(request.NativeManifest);
        if (manifest.SchemaVersion != 2 || manifest.Files.Any(f => !Files.ValidRelativePath(f.Path)) ||
            manifest.Files.Select(f => f.Path).Distinct(StringComparer.Ordinal).Count() != manifest.Files.Length ||
            !request.NativeFiles.Select(f => f.Destination)
                .Order(StringComparer.Ordinal).SequenceEqual(manifest.Files.Select(f => f.Path).Order(StringComparer.Ordinal)))
            throw new InvalidDataException("native runtime closure declaration mismatch");
        var expected = manifest.Files.ToDictionary(f => f.Path, StringComparer.Ordinal);
        foreach (var file in request.NativeFiles)
        {
            var entry = expected[file.Destination];
            Files.Verify(file.Source, entry.Size, entry.Sha256,
                "native runtime closure payload mismatch: " + file.Destination);
        }
    }

}
