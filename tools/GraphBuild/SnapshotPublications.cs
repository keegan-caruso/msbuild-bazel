namespace RulesMSBuild.GraphBuild;

// One graph invocation owns publication. Capture remains serial and immutable;
// at most two independent snapshot publications overlap local capture. Disposal
// drains every started task, including after capture or publication failures.
internal sealed class SnapshotPublications(int capacity = 2) : IAsyncDisposable
{
    private readonly List<Task> pending = [];

    internal async Task Add(Func<Task> publish)
    {
        if (capacity < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(capacity));
        }
        if (pending.Count >= capacity)
        {
            var complete = await Task.WhenAny(pending);
            pending.Remove(complete);
            await complete;
        }
        pending.Add(publish());
    }

    public async ValueTask DisposeAsync() => await Task.WhenAll(pending);
}
