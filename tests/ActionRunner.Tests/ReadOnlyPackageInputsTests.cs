using ActionRunner;
using NativeCache;

internal static class ReadOnlyPackageInputsTests
{
    public static void Run()
    {
        if (OperatingSystem.IsWindows()) return;
        var root = Directory.CreateTempSubdirectory("borrowed-package-test-").FullName;
        var source = Path.Combine(root, "source");
        var stage = Path.Combine(root, "stage");
        try
        {
            File.WriteAllText(source, "original");
            var inputs = new ReadOnlyPackageInputs();
            try
            {
                inputs.Link(source, Path.Combine(stage, "writable"), Files.Hash(source));
                throw new InvalidOperationException("Writable package accepted");
            }
            catch (InvalidDataException) { }
            File.SetUnixFileMode(source, UnixFileMode.UserRead);
            inputs.Link(source, Path.Combine(stage, "package"), Files.Hash(source));
            inputs.VerifyUnchanged();
            ReadOnlyPackageInputs.VerifyAlias(Path.Combine(stage, "package"), source);
            if (inputs.Aliases(stage).Count != 1) throw new InvalidOperationException("Borrowed alias missing");
            var replacement = Path.Combine(root, "replacement");
            File.WriteAllText(replacement, "original");
            File.SetUnixFileMode(replacement, UnixFileMode.UserRead);
            File.Delete(Path.Combine(stage, "package"));
            File.CreateSymbolicLink(Path.Combine(stage, "package"), replacement);
            try
            {
                ReadOnlyPackageInputs.VerifyAlias(Path.Combine(stage, "package"), source);
                throw new InvalidOperationException("Retargeted package alias accepted");
            }
            catch (InvalidDataException) { }
            File.Delete(Path.Combine(stage, "package"));
            File.WriteAllText(Path.Combine(stage, "package"), "original");
            if (inputs.Aliases(stage).Count != 0) throw new InvalidOperationException("Private replacement treated as borrowed");
            File.Delete(Path.Combine(stage, "package"));
            File.CreateSymbolicLink(Path.Combine(stage, "package"), source);
            if (File.ReadAllText(Path.Combine(stage, "package")) != "original") throw new InvalidOperationException("Package content changed");
            File.SetUnixFileMode(source, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            File.WriteAllText(source, "modified");
            try
            {
                inputs.VerifyUnchanged();
                throw new InvalidOperationException("Package mutation accepted");
            }
            catch (InvalidDataException) { }
            Directory.Delete(stage, true);
            if (File.ReadAllText(source) != "modified") throw new InvalidOperationException("Cleanup removed package source");
        }
        finally
        {
            if (File.Exists(source)) File.SetUnixFileMode(source, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            Directory.Delete(root, true);
        }
    }
}
