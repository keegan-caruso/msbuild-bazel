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
