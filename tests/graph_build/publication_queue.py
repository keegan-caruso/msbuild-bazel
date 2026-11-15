"""Publication overlaps capture, stays bounded and drains after failures."""
from pathlib import Path
import tempfile
from qualify import DOTNET, ROOT, run


def main():
    with tempfile.TemporaryDirectory(prefix='publication-queue-') as temporary:
        work = Path(temporary)
        source = ROOT/'tools/GraphBuild/SnapshotPublications.cs'
        (work/'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings>'
            '<Nullable>enable</Nullable></PropertyGroup><ItemGroup>' + f'<Compile Include="{source}" />' + '</ItemGroup></Project>')
        (work/'Program.cs').write_text('''using RulesMSBuild.GraphBuild;
var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
int active = 0, peak = 0, finished = 0;
async Task Publish() { active++; peak = Math.Max(peak, active); await release.Task; active--; finished++; }
await using (var queue = new SnapshotPublications())
{
    await queue.Add(Publish);
    await queue.Add(Publish);
    if (active != 2 || finished != 0) throw new Exception("Did not overlap capture");
    var third = queue.Add(Publish);
    if (third.IsCompleted || peak != 2) throw new Exception("Unbounded publication");
    release.SetResult();
    await third;
}
if (finished != 3 || peak != 2) throw new Exception("Did not drain publications");
bool drained = false, rejected = false;
try
{
    await using var queue = new SnapshotPublications();
    await queue.Add(() => Task.FromException(new IOException("publication failed")));
    await queue.Add(async () => { await Task.Delay(50); drained = true; });
    await queue.Add(() => Task.CompletedTask);
}
catch (IOException) { rejected = true; }
if (!drained || !rejected) throw new Exception("Failure lost or outstanding publication escaped");
bool captureDrained = false;
try
{
    await using var queue = new SnapshotPublications();
    await queue.Add(async () => { await Task.Delay(50); captureDrained = true; });
    throw new InvalidDataException("capture failed");
}
catch (InvalidDataException) { }
if (!captureDrained) throw new Exception("Capture failure did not drain");
Console.WriteLine("PASS: overlapping capture, capacity2, publication/capture failure drain");
''')
        run(DOTNET, 'build', work/'Probe.csproj', '-c', 'Release')
        result = run(DOTNET, work/'bin/Release/net10.0/Probe.dll')
        print(result.stdout.strip())


if __name__ == '__main__':
    main()
