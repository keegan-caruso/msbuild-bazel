"""Shared declaration defaults for the integration qualification suite."""

load("@bazel_binaries//:defs.bzl", "bazel_binaries")
load("@rules_bazel_integration_test//bazel_integration_test:defs.bzl", "bazel_integration_tests", "integration_test_utils")
load("@rules_shell//shell:sh_binary.bzl", "sh_binary")

def integration_runner(name, srcs, data = ["common.sh"]):
    """Declare an integration shell runner with its exact runfiles."""
    sh_binary(name = name, testonly = True, srcs = srcs, data = data)

def integration_case(name, test_runner, workspace_files = ["//:quickstart_sources"], workspace_path = "examples/quickstart", data = [":rules_archive"], env = {}, additional_env_inherit = ["BAZELISK_HOME", "RULES_MSBUILD_TEST_REPOSITORY_CACHE"], target_compatible_with = []):
    """Declare a case for every pinned Bazel with isolated nested-build defaults."""
    bazel_integration_tests(
        name = name,
        additional_env_inherit = additional_env_inherit,
        bazel_binaries = bazel_binaries,
        bazel_versions = bazel_binaries.versions.all,
        data = data,
        env = dict({"RULES_ARCHIVE": "$(rootpath :rules_archive)"}, **env),
        tags = ["exclusive", "manual", "no-sandbox"],
        target_compatible_with = target_compatible_with,
        test_runner = test_runner,
        workspace_files = workspace_files,
        workspace_path = workspace_path,
    )

def integration_suite(name, cases):
    """Keep manual suite membership explicit, including suites with several cases."""
    native.test_suite(
        name = name,
        tags = ["manual"],
        tests = [test for case in cases for test in integration_test_utils.bazel_integration_test_names(case, bazel_binaries.versions.all)],
    )
