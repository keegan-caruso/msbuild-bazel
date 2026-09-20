using ActionRunner;

internal static class WorkerInputsTests
{
    internal static void Run()
    {
        if (!OperatingSystem.IsLinux()) return;
        var root = Directory.CreateTempSubdirectory("worker-input-tests-").FullName;
        try
        {
            var source = Path.Combine(root, "source");
            var target = Path.Combine(root, "current");
            var store = new WorkerInputs(Path.Combine(root, "cas"), true, limit: 4);
            void Require(bool value) { if (!value) throw new InvalidOperationException("Worker input cache contract failed"); }
            File.WriteAllText(source, "aaaa");
            var first = Files.Hash(source);
            store.Begin(); store.Stage(source, target, first);
            Require(store.VerifiedBytes == 4 && store.ReusedBytes == 0);
            File.Delete(target);
            // The stored snapshot is independent of the original source inode.
            File.WriteAllText(source, "bbbb");
            var second = Files.Hash(source);
            store.Begin(); store.Stage(source, target, first);
            Require(File.ReadAllText(target) == "aaaa" && store.ReusedBytes == 4 && store.VerifiedBytes == 0);
            File.Delete(target);
            store.Begin(); store.Stage(source, target, second);
            Require(File.ReadAllText(target) == "bbbb" && store.VerifiedBytes == 4);
            File.Delete(target);
            // The four-byte store evicted the first identity. A mismatched input
            // must now fail verification, rather than poisoning the store.
            try { store.Stage(source, target, first); throw new InvalidOperationException("Accepted mismatched input"); }
            catch (InvalidDataException) { }
            Require(!File.Exists(target));
            File.SetUnixFileMode(source, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
            store.Stage(source, target, second);
            Require((File.GetUnixFileMode(target) & UnixFileMode.UserExecute) != 0);
            Require((File.GetUnixFileMode(target) & UnixFileMode.UserWrite) == 0);
            Files.ReadOnlyInputs = new Dictionary<string, Files.VerifiedInput> { [target] = new(4, second) };
            Files.Verify(target, 4, second, "valid snapshot");
            try { Files.Verify(target, 5, second, "size mismatch"); throw new InvalidOperationException("Accepted wrong size"); }
            catch (InvalidDataException) { }
            try { Files.Verify(target, 4, first, "digest mismatch"); throw new InvalidOperationException("Accepted wrong digest"); }
            catch (InvalidDataException) { }
            // An unindexed mutable file still gets full byte validation.
            Require(Files.Hash(source) == second);
            File.WriteAllText(source, "cccc");
            Require(Files.Hash(source) != second);
        }
        finally { Files.ReadOnlyInputs = null; Directory.Delete(root, true); }
    }
}
