using System.Buffers.Binary;
using System.Diagnostics;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

internal static class TestSharding
{
    internal static (int Total, int Index)? Configuration()
    {
        var totalText = Environment.GetEnvironmentVariable("TEST_TOTAL_SHARDS");
        var indexText = Environment.GetEnvironmentVariable("TEST_SHARD_INDEX");
        if (totalText is null && indexText is null)
        {
            return null;
        }
        if (!int.TryParse(totalText, NumberStyles.None, CultureInfo.InvariantCulture, out var total) || total < 1 ||
            !int.TryParse(indexText, NumberStyles.None, CultureInfo.InvariantCulture, out var index) || index >= total)
        {
            throw new InvalidDataException("Invalid TEST_TOTAL_SHARDS/TEST_SHARD_INDEX");
        }
        return (total, index);
    }

    internal static bool Configure(ProcessStartInfo start, TestOptions options, string stagingRoot)
    {
        if (Configuration() is not { } shard)
        {
            return true;
        }
        var (total, index) = shard;
        var discovery = new ProcessStartInfo(start.FileName)
        {
            WorkingDirectory = start.WorkingDirectory,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        discovery.Environment.Clear();
        foreach (var pair in start.Environment)
        {
            discovery.Environment[pair.Key] = pair.Value;
        }
        var arguments = start.ArgumentList.ToArray();
        var list = Path.Combine(stagingRoot, "discovered-tests.txt");
        for (var i = 0; i < arguments.Length; i++)
        {
            var argument = arguments[i];
            if (options.Protocol == "mtp" && argument is "--report-trx" or "--report-trx-filename" or "--results-directory")
            {
                if (argument != "--report-trx")
                {
                    i++;
                }
                continue;
            }
            if (options.Protocol == "vstest" && (argument.StartsWith("/Logger:", StringComparison.OrdinalIgnoreCase) || argument.StartsWith("/ResultsDirectory:", StringComparison.OrdinalIgnoreCase)))
            {
                continue;
            }
            if (argument == "--" && options.Protocol == "vstest")
            {
                discovery.ArgumentList.Add("/ListFullyQualifiedTests");
                discovery.ArgumentList.Add("/ListTestsTargetPath:" + list);
            }
            discovery.ArgumentList.Add(argument);
        }
        if (options.Protocol == "mtp")
        {
            discovery.ArgumentList.Add("--list-tests");
            discovery.ArgumentList.Add("json");
            discovery.ArgumentList.Add("--no-banner");
        }
        var result = TestExecution.Execute(discovery);
        if (result.ExitCode != 0)
        {
            throw new InvalidDataException("Test shard discovery failed (MTP requires structured JSON discovery in version 2.3 or later): " + result.Error + result.Output);
        }
        string[] names;
        var identities = new Dictionary<string, string>(StringComparer.Ordinal);
        if (options.Protocol == "mtp")
        {
            using var document = JsonDocument.Parse(result.Output);
            if (document.RootElement.GetProperty("schemaVersion").GetInt32() != 1)
            {
                throw new InvalidDataException("Unsupported MTP discovery schema");
            }
            foreach (var test in document.RootElement.GetProperty("tests").EnumerateArray())
            {
                var uid = test.GetProperty("uid").GetString() ?? throw new InvalidDataException("Missing discovered test UID");
                var name = test.GetProperty("displayName").GetString() ?? throw new InvalidDataException("Missing discovered test display name");
                if (identities.TryGetValue(uid, out var previous) && previous != name)
                {
                    throw new InvalidDataException("Conflicting discovered test UID");
                }
                identities[uid] = name;
            }
            if (identities.Values.Any(string.IsNullOrWhiteSpace))
            {
                throw new InvalidDataException("Missing discovered test display name");
            }
            names = identities.Keys.ToArray();
        }
        else
        {
            // VSTest filters are case-insensitive; group equivalent names on
            // the same shard, including parameterized cases sharing one FQN.
            names = File.ReadAllLines(list).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        }
        if (names.Any(name => string.IsNullOrWhiteSpace(name) || name.IndexOfAny(['\0', '\r', '\n']) >= 0))
        {
            throw new InvalidDataException("Invalid discovered test name");
        }
        if (Environment.GetEnvironmentVariable("TEST_SHARD_STATUS_FILE") is { } status)
        {
            File.WriteAllText(status, "");
        }
        if (options.Protocol == "vstest" && names.Length == 0 &&
            start.ArgumentList.Any(argument => argument.StartsWith("/TestCaseFilter:", StringComparison.OrdinalIgnoreCase)))
        {
            // Some adapters expose data rows only during execution. A filtered
            // discovery miss cannot distinguish those rows from a truly empty
            // suite: execute the original filter once, preserving its zero-test
            // policy, instead of broadening it or inventing success.
            Console.WriteLine("VSTest filter was not resolved by discovery; only shard 0 executes the original filter");
            return index == 0;
        }
        if (names.Length == 0 && !options.AllowEmpty)
        {
            throw new InvalidDataException("No tests were discovered for sharding");
        }
        // Framework UIDs may include the physical assembly path, which differs
        // in each shard's private staging directory. Partition by display name;
        // colliding display names stay together, but execute every distinct UID.
        var selected = names.Where(name => Partition(options.Protocol == "mtp" ? identities[name] : name.ToUpperInvariant(), total) == index)
            .Order(StringComparer.Ordinal).ToArray();
        Console.WriteLine("Bazel shard " + index + "/" + total + ": selected " + selected.Length + " of " + names.Length + " discovered test identities");
        if (selected.Length == 0)
        {
            return false;
        }
        if (options.Protocol == "mtp")
        {
            // Discovery applied the caller's framework filter already. Select
            // only the resulting UIDs rather than combining incompatible filters.
            for (var i = start.ArgumentList.Count - 2; i >= 0; i--)
            {
                if (start.ArgumentList[i] == options.FilterArgument && options.FilterArgument.Length != 0)
                {
                    start.ArgumentList.RemoveAt(i + 1);
                    start.ArgumentList.RemoveAt(i);
                }
            }
            start.ArgumentList.Add("--filter-uid");
            foreach (var name in selected)
            {
                start.ArgumentList.Add(name);
            }
        }
        else
        {
            var selectedFilter = "(" + string.Join('|', selected.Select(name => "FullyQualifiedName=" + Escape(name))) + ")";
            var existing = start.ArgumentList.Select((value, position) => (value, position))
                .Where(argument => argument.value.StartsWith("/TestCaseFilter:", StringComparison.OrdinalIgnoreCase)).ToArray();
            if (existing.Length > 1)
            {
                throw new InvalidDataException("Multiple VSTest filters are not supported");
            }
            if (existing.Length == 1)
            {
                // Parameterized rows can share an FQN but differ in display
                // name or traits. Keep the caller's constraint at execution.
                var original = existing[0].value["/TestCaseFilter:".Length..];
                start.ArgumentList[existing[0].position] = "/TestCaseFilter:(" + original + ")&" + selectedFilter;
            }
            else
            {
                var position = start.ArgumentList.IndexOf("--");
                start.ArgumentList.Insert(position < 0 ? start.ArgumentList.Count : position, "/TestCaseFilter:" + selectedFilter);
            }
        }
        return true;
    }

    private static int Partition(string identity, int total)
    {
        var digest = SHA256.HashData(Encoding.UTF8.GetBytes(identity));
        return (int)(BinaryPrimitives.ReadUInt32BigEndian(digest) % (uint)total);
    }

    private static string Escape(string value) => string.Concat(value.Select(character => "\\()&|=!~".Contains(character) ? "\\" + character : character.ToString()));
}
