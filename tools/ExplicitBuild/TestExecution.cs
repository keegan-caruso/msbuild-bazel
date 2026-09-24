using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Xml;
using System.Xml.Linq;

internal sealed record TestOptions(string Protocol = "executable", string? Settings = null, string FilterArgument = "", bool AllowEmpty = false, string? Runner = null, string[]? Adapters = null, bool Diagnostics = false, string[]? OutputDirectories = null, string? SettingsOutput = null);

internal static class TestExecution
{
    internal static void Validate(TestOptions options)
    {
        if (options.Protocol is not ("executable" or "mtp" or "vstest"))
        {
            throw new InvalidDataException("Unknown test protocol: " + options.Protocol);
        }

        if (int.TryParse(Environment.GetEnvironmentVariable("TEST_TOTAL_SHARDS"), out var count) && count > 1)
        {
            throw new InvalidDataException("Test sharding is not supported");
        }

        if (options.Protocol == "executable" && (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("TESTBRIDGE_TEST_ONLY")) || (options.Settings is not null || options.SettingsOutput is not null)))
        {
            throw new InvalidDataException("Executable test filtering/settings is not supported");
        }

        if (options.Settings is not null && options.SettingsOutput is not null)
        {
            throw new InvalidDataException("Declare either test_settings or test_settings_output");
        }

        if (options.SettingsOutput is not null)
        {
            Program.Safe(options.SettingsOutput);
        }

        if (options.FilterArgument is not ("" or "--filter" or "--filter-query"))
        {
            throw new InvalidDataException("Unsupported MTP filter argument");
        }
    }

    internal static int Run(ProcessStartInfo start, TestOptions options, string runfiles)
    {
        var protocol = options.Protocol;
        var output = Environment.GetEnvironmentVariable("TEST_UNDECLARED_OUTPUTS_DIR") ?? Path.Combine(start.WorkingDirectory, "test-results");
        output = Path.GetFullPath(output);
        Directory.CreateDirectory(output);
        var report = Path.Combine(output, "results.trx");
        var xml = Environment.GetEnvironmentVariable("XML_OUTPUT_FILE");
        var watch = Stopwatch.StartNew();
        var exitCode = 0;
        try
        {
            foreach (var directory in options.OutputDirectories ?? [])
            {
                var relative = Program.Safe(directory);
                var target = Path.Combine(output, "files", relative);
                var link = Path.Combine(start.WorkingDirectory, relative);
                if (Directory.Exists(link) || File.Exists(link))
                {
                    throw new InvalidDataException("Test output directory collides with a runtime input: " + relative);
                }

                Directory.CreateDirectory(target);
                Directory.CreateDirectory(Path.GetDirectoryName(link)!);
                Directory.CreateSymbolicLink(link, target);
            }
            var settings = options.SettingsOutput is not null
                ? Path.Combine(start.WorkingDirectory, Program.Safe(options.SettingsOutput))
                : options.Settings is not null ? Path.Combine(runfiles, Program.Safe(options.Settings)) : null;
            if (settings is not null && !File.Exists(settings))
            {
                throw new InvalidDataException("Missing declared test settings: " + settings);
            }

            if (protocol == "mtp")
            {
                // Own the reporting destination: arbitrary arguments must not disable or redirect it.
                foreach (var argument in start.ArgumentList.Skip(1))
                {
                    if (new[] { "--report-trx", "--results-directory", "--minimum-expected-tests", "--ignore-exit-code", "--list-tests", "--help", "--config-file" }.Any(option => argument.Split('=')[0].StartsWith(option, StringComparison.Ordinal)))
                    {
                        throw new InvalidDataException("Test argument is controlled by the Bazel test adapter: " + argument);
                    }
                }

                Add(start, "--report-trx", "--report-trx-filename", "results.trx", "--results-directory", output);
                if (settings is not null)
                {
                    Add(start, "--config-file", settings);
                }

                var filter = Environment.GetEnvironmentVariable("TESTBRIDGE_TEST_ONLY");
                if (!string.IsNullOrEmpty(filter))
                {
                    if (options.FilterArgument.Length == 0)
                    {
                        throw new InvalidDataException("MTP filtering requires an explicit test_filter_argument supported by the test framework");
                    }

                    Add(start, options.FilterArgument, filter);
                }
            }
            if (protocol == "vstest")
            {
                foreach (var argument in start.ArgumentList.Skip(1))
                {
                    if (new[] { "/logger", "--logger", "/resultsdirectory", "--resultsdirectory", "/listtests", "--listtests", "/settings", "--settings", "/testadapterpath", "--testadapterpath", "/testadapterloadingstrategy", "--testadapterloadingstrategy", "/?", "--help", "--" }.Contains(argument.Split(':', '=')[0], StringComparer.OrdinalIgnoreCase))
                    {
                        throw new InvalidDataException("Test argument is controlled by the Bazel test adapter: " + argument);
                    }
                }

                if (options.Runner is null)
                {
                    throw new InvalidDataException("VSTest requires an explicit runner");
                }

                start.ArgumentList.Insert(0, Path.Combine(runfiles, Program.Safe(options.Runner)));
                Add(start, "/Logger:trx;LogFileName=results.trx", "/ResultsDirectory:" + output);
                if (options.Diagnostics)
                {
                    Add(start, "/Diag:" + Path.Combine(output, "vstest.log"));
                }

                if (settings is not null)
                {
                    Add(start, "/Settings:" + settings);
                }

                if (options.Adapters is { Length: > 0 })
                {
                    var adapters = options.Adapters.Select(p => Path.Combine(runfiles, Program.Safe(p))).ToArray();
                    foreach (var adapter in adapters)
                    {
                        if (!Directory.Exists(adapter))
                        {
                            throw new InvalidDataException("Missing declared test adapter directory: " + adapter);
                        }
                    }
                    // DotnetTestHostManager discovers adapters beside the test
                    // assembly, even when the console has TestAdapterPath set.
                    // Compose the declared adapter files with collision checks.
                    foreach (var adapter in adapters)
                    {
                        foreach (var file in Directory.GetFiles(adapter, "*", SearchOption.AllDirectories))
                        {
                            Program.Copy(file, Path.Combine(start.WorkingDirectory, Program.Safe(Path.GetRelativePath(adapter, file).Replace('\\', '/'))));
                        }
                    }

                    Add(start, "/TestAdapterPath:" + string.Join(';', adapters));
                }
                var filter = Environment.GetEnvironmentVariable("TESTBRIDGE_TEST_ONLY");
                if (!string.IsNullOrEmpty(filter))
                {
                    Add(start, "/TestCaseFilter:" + filter);
                }
                // VSTest launches another dotnet process; the declared host must
                // also govern that child instead of a path in captured settings.
                Add(start, "--", "RunConfiguration.DotNetHostPath=" + start.FileName);
            }
            var cancelled = 0;
            using var process = Process.Start(start) ?? throw new InvalidDataException("Test process could not start");
            void Cancel(PosixSignalContext context)
            {
                context.Cancel = true;
                Interlocked.Exchange(ref cancelled, 1);
                try
                {
                    if (!process.HasExited)
                    {
                        process.Kill(entireProcessTree: true);
                    }
                }
                catch (InvalidOperationException) { /* The child exited concurrently. */ }
            }
            using var terminate = PosixSignalRegistration.Create(PosixSignal.SIGTERM, Cancel);
            using var interrupt = PosixSignalRegistration.Create(PosixSignal.SIGINT, Cancel);
            process.WaitForExit();
            exitCode = process.ExitCode;
            if (cancelled != 0)
            {
                throw new InvalidDataException("Test run cancelled");
            }

            if (protocol == "executable")
            {
                return process.ExitCode;
            }

            return Report(report, xml, process.ExitCode, options.AllowEmpty, protocol == "mtp", watch.Elapsed);
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("Test runner error: " + error.Message);
            Write(xml, [Error("runner", error.Message)], watch.Elapsed);
            return exitCode != 0 ? exitCode : 1;
        }
    }

    private static void Add(ProcessStartInfo start, params string[] arguments)
    {
        foreach (var argument in arguments)
        {
            start.ArgumentList.Add(argument);
        }
    }

    private static XElement Error(string name, string message) => new("testcase", new XAttribute("name", name), new XAttribute("classname", "Bazel.TestRunner"), new XElement("error", new XAttribute("message", message), message));

    private static int Report(string report, string? output, int exit, bool allowEmpty, bool mtp, TimeSpan elapsed)
    {
        using var reader = XmlReader.Create(report, new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null });
        var document = XDocument.Load(reader);
        XNamespace ns = "http://microsoft.com/schemas/VisualStudio/TeamTest/2010";
        var root = document.Root;
        if (root?.Name != ns + "TestRun" || root.Element(ns + "ResultSummary") is null)
        {
            throw new InvalidDataException("Incomplete or invalid TRX report");
        }

        var definitions = root.Element(ns + "TestDefinitions")?.Elements(ns + "UnitTest").Where(e => e.Attribute("id") is not null).ToDictionary(e => (string)e.Attribute("id")!, e => (string?)e.Element(ns + "TestMethod")?.Attribute("className") ?? "") ?? [];
        var cases = new List<XElement>();
        if (root.Element(ns + "Results")?.Elements().Any(e => e.Name != ns + "UnitTestResult") == true)
        {
            throw new InvalidDataException("Unsupported TRX result type");
        }

        foreach (var result in root.Element(ns + "Results")?.Elements(ns + "UnitTestResult") ?? [])
        {
            var name = (string?)result.Attribute("testName") ?? throw new InvalidDataException("TRX result has no test name");
            var outcome = (string?)result.Attribute("outcome") ?? throw new InvalidDataException("TRX result has no outcome");
            var duration = (string?)result.Attribute("duration");
            var seconds = duration is null ? 0 : TimeSpan.Parse(duration, CultureInfo.InvariantCulture).TotalSeconds;
            var test = new XElement("testcase", new XAttribute("name", name), new XAttribute("classname", definitions.GetValueOrDefault((string?)result.Attribute("testId") ?? "", "")), new XAttribute("time", seconds.ToString("R", CultureInfo.InvariantCulture)));
            var details = result.Element(ns + "Output");
            var message = (string?)details?.Element(ns + "ErrorInfo")?.Element(ns + "Message") ?? outcome;
            var stack = (string?)details?.Element(ns + "ErrorInfo")?.Element(ns + "StackTrace") ?? "";
            if (outcome == "Failed")
            {
                test.Add(new XElement("failure", new XAttribute("message", message), message + "\n" + stack));
            }
            else if (outcome is "NotExecuted" or "Inconclusive")
            {
                test.Add(new XElement("skipped", new XAttribute("message", message)));
            }
            else if (outcome != "Passed")
            {
                test.Add(new XElement("error", new XAttribute("message", message), message + "\n" + stack));
            }

            foreach (var (source, target) in new[] { ("StdOut", "system-out"), ("StdErr", "system-err") })
            {
                if (details?.Element(ns + source) is { } stream)
                {
                    test.Add(new XElement(target, stream.Value));
                }
            }

            cases.Add(test);
        }
        var total = (string?)root.Element(ns + "ResultSummary")?.Element(ns + "Counters")?.Attribute("total");
        if (total is not null && (!int.TryParse(total, NumberStyles.None, CultureInfo.InvariantCulture, out var expected) || expected != cases.Count))
        {
            throw new InvalidDataException("Incomplete TRX report: result count disagrees with summary");
        }
        // MTP reserves exit 8 for zero discovered tests. Only the explicit empty
        // policy plus a valid empty report may turn that particular exit into success.
        if (allowEmpty && mtp && exit == 8 && cases.Count == 0)
        {
            Write(output, cases, elapsed);
            return 0;
        }
        if (cases.Count == 0 && !allowEmpty)
        {
            cases.Add(Error("discovery", "No tests were found; set allow_empty_tests only for intentionally empty suites"));
        }

        var summary = root.Element(ns + "ResultSummary")!;
        var failed = cases.Any(c => c.Element("failure") is not null || c.Element("error") is not null);
        if (!failed && ((string?)summary.Attribute("outcome") is not ("Completed" or "Passed") || exit != 0))
        {
            cases.Add(Error("runner", "Test runner did not complete successfully (exit " + exit + ", outcome " + (string?)summary.Attribute("outcome") + ")"));
        }

        Write(output, cases, elapsed);
        return exit != 0 ? exit : cases.Any(c => c.Element("failure") is not null || c.Element("error") is not null) ? 1 : 0;
    }

    private static void Write(string? path, IEnumerable<XElement> results, TimeSpan elapsed)
    {
        if (string.IsNullOrEmpty(path))
        {
            return;
        }

        var cases = results.ToArray();
        var suite = new XElement("testsuite", new XAttribute("name", Environment.GetEnvironmentVariable("TEST_TARGET") ?? "msbuild_test"), new XAttribute("tests", cases.Length), new XAttribute("failures", cases.Count(c => c.Element("failure") is not null)), new XAttribute("errors", cases.Count(c => c.Element("error") is not null)), new XAttribute("skipped", cases.Count(c => c.Element("skipped") is not null)), new XAttribute("time", elapsed.TotalSeconds.ToString("R", CultureInfo.InvariantCulture)), cases);
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        new XDocument(new XElement("testsuites", suite)).Save(path);
    }
}
