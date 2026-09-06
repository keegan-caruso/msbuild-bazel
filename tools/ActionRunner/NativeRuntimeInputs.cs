namespace ActionRunner;

internal static class NativeRuntimeInputs
{
    public static void Validate(ActionRequest request)
    {
        if (request.NativeManifest is null) return;
        var manifest = JsonFiles.Read<NativeManifest>(request.NativeManifest);
        if (manifest.SchemaVersion != 1 || !request.NativeFiles.Select(f => f.Destination)
                .Order(StringComparer.Ordinal).SequenceEqual(manifest.Files.Order(StringComparer.Ordinal)))
            throw new InvalidDataException("native runtime closure declaration mismatch");
        foreach (var file in request.NativeFiles)
            if (!File.Exists(file.Source))
                throw new FileNotFoundException("native runtime closure file missing: " + file.Destination);
    }

}
