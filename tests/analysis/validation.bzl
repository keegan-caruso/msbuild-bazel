"""Invalid declarations rejected before any compilation starts."""

load("//msbuild:defs.bzl", "msbuild_binary", "msbuild_file_binding", "msbuild_generate", "msbuild_test", "msbuild_tool")
load(":helpers.bzl", "failure_test", "library")

def validation_tests(name):
    """Declare validation tests.

    Args:
        name: Prefix for test names.
    """
    for case, attrs, message in [
        ("settings_conflict", {"test_settings": "settings.xml", "test_settings_output": "generated.xml"}, "Declare either test_settings or test_settings_output"),
        ("settings_escape", {"test_settings_output": "../outside.xml"}, "test_settings_output must be a safe relative path"),
        ("sharding", {"shard_count": 2}, "Executable tests do not yet support sharding"),
        ("vstest_runner", {"test_protocol": "vstest"}, "VSTest requires an explicit test_runner"),
        ("diagnostics", {"test_diagnostics": True}, "test_diagnostics currently requires VSTest"),
        ("reference_test", {"output_mode": "reference"}, "Reference-only projects cannot execute"),
    ]:
        subject = name + "_" + case + "_subject"
        msbuild_test(name = subject, project = "Tests.csproj", target_framework = "net10.0", tags = ["manual"], **attrs)
        failure_test(name + "_" + case, ":" + subject, message)
    for case, attrs, message in [
        ("entry", {"entry_point": "../Tasks.dll"}, "Tool entry_point must be a safe relative file path"),
        ("prefix", {"layout_prefix": "../net"}, "Tool layout_prefix must be a safe relative path"),
    ]:
        subject = name + "_" + case + "_subject"
        msbuild_tool(name = subject, assembly = ":task", tags = ["manual"], **attrs)
        failure_test(name + "_" + case, ":" + subject, message)
    library("unbound", bindings = [":binding"])
    failure_test(name + "_unbound", ":unbound", "Bound tool must also be declared in tools")
    library("duplicate_binding", tools = [":tool"], bindings = [":binding", ":binding_again"])
    msbuild_file_binding(name = "binding_again", tool = ":tool", property_name = "tasklocation", tags = ["manual"])
    failure_test(name + "_duplicate_binding", ":duplicate_binding", "Duplicate bound property")
    for case, outputs, targets, message in [
        ("escape", ["../bad.cs"], ["Generate"], "Generated outputs require safe relative paths"),
        ("duplicate", ["A.cs", "A.cs"], ["Generate"], "Duplicate generated output"),
        ("empty", [], ["Generate"], "Generation requires explicit targets and outputs"),
    ]:
        subject = name + "_generate_" + case
        msbuild_generate(name = subject, project = "Generate.csproj", target_framework = "net10.0", outputs = outputs, targets = targets, tags = ["manual"])
        failure_test(subject + "_test", ":" + subject, message)
    msbuild_binary(name = "direct_binary", project = "App.csproj", target_framework = "net10.0", transitive_compile_references = False, tags = ["manual"])
    failure_test(name + "_direct_binary", ":direct_binary", "Direct-only compilation references are supported only for libraries")
    library("restore_mismatch", restore = ":restore", configuration = "Debug")
    failure_test(name + "_restore", ":restore_mismatch", "Shared restore framework/configuration/output kind must match")
