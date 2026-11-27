using System.Diagnostics;
using System.Globalization;
using System.Text;

internal sealed class TestCoverage(TestOptions options, string reports, string destination)
{
    internal static TestCoverage? Create(TestOptions options, string reports)
    {
        if (Environment.GetEnvironmentVariable("COVERAGE_OUTPUT_FILE") is not { Length: > 0 } destination)
        {
            return null;
        }
        if (options.Coverage != "coverlet")
        {
            throw new InvalidDataException("Bazel coverage requires test_coverage = \"coverlet\" and its declared collector package");
        }
        var coverage = new TestCoverage(options, reports, Path.GetFullPath(destination));
        // A failed collector must not leave an earlier invocation's report.
        coverage.WriteEmpty();
        return coverage;
    }

    internal void Configure(ProcessStartInfo start, string protocol)
    {
        if (protocol == "mtp")
        {
            foreach (var argument in start.ArgumentList)
            {
                if (argument.StartsWith("--coverlet", StringComparison.Ordinal))
                {
                    throw new InvalidDataException("Coverlet options are controlled by the Bazel coverage adapter");
                }
            }
            foreach (var argument in new[] { "--coverlet", "--coverlet-output-format", "lcov", "--coverlet-file-prefix", "bazel", "--coverlet-exclude-assemblies-without-sources", "None" })
            {
                start.ArgumentList.Add(argument);
            }
        }
        else
        {
            if (start.ArgumentList.Any(argument => new[] { "/collect", "--collect" }.Contains(argument.Split(':', '=')[0], StringComparer.OrdinalIgnoreCase)))
            {
                throw new InvalidDataException("Coverage collection is controlled by the Bazel coverage adapter");
            }
            var position = start.ArgumentList.IndexOf("--");
            start.ArgumentList.Insert(position < 0 ? start.ArgumentList.Count : position, "/Collect:XPlat Code Coverage;Format=lcov;ExcludeAssembliesWithoutSources=None");
        }
    }

    internal void WriteEmpty()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        File.WriteAllText(destination, "");
    }

    internal void Finish(bool empty)
    {
        var result = new StringBuilder();
        var found = false;
        foreach (var report in Directory.EnumerateFiles(reports, "*.info", SearchOption.AllDirectories).Order(StringComparer.Ordinal))
        {
            var record = new List<string>();
            foreach (var line in File.ReadLines(report))
            {
                if (record.Count == 0 && string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }
                record.Add(line);
                if (line != "end_of_record")
                {
                    continue;
                }
                var sources = record.Where(value => value.StartsWith("SF:", StringComparison.Ordinal)).ToArray();
                if (sources.Length != 1)
                {
                    throw new InvalidDataException("Invalid LCOV source record");
                }
                var source = sources[0][3..].Replace('\\', '/');
                const string prefix = "/_/workspace/";
                if (source.StartsWith(prefix, StringComparison.Ordinal) && options.CoverageSources?.TryGetValue(source[prefix.Length..], out var mapped) == true)
                {
                    Program.Safe(mapped);
                    if (!record.Any(value => value.StartsWith("DA:", StringComparison.Ordinal)))
                    {
                        throw new InvalidDataException("LCOV source record contains no instrumented lines");
                    }
                    foreach (var value in record)
                    {
                        if (value.StartsWith("DA:", StringComparison.Ordinal))
                        {
                            var fields = value[3..].Split(',');
                            if (fields.Length is not (2 or 3) ||
                                !int.TryParse(fields[0], NumberStyles.None, CultureInfo.InvariantCulture, out var number) || number < 1 ||
                                !long.TryParse(fields[1], NumberStyles.None, CultureInfo.InvariantCulture, out _))
                            {
                                throw new InvalidDataException("Invalid LCOV line counter");
                            }
                        }
                        result.Append(value.StartsWith("SF:", StringComparison.Ordinal) ? "SF:" + mapped : value).Append('\n');
                    }
                    found = true;
                }
                record.Clear();
            }
            if (record.Count != 0)
            {
                throw new InvalidDataException("Incomplete LCOV record");
            }
        }
        if (!found && !empty)
        {
            throw new InvalidDataException("Collector emitted no LCOV coverage for declared graph sources");
        }
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        File.WriteAllText(destination, result.ToString());
    }
}
