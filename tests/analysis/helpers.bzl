"""Shared analysis assertions; fixtures never execute an MSBuild action."""

load("@rules_testing//lib:analysis_test.bzl", "analysis_test")
load("@rules_testing//lib:truth.bzl", "matching")
load("@rules_testing//lib:util.bzl", "TestingAspectInfo")
load("//msbuild:defs.bzl", "msbuild_library")

def library(name, **kwargs):
    msbuild_library(name = name, project = name + ".csproj", target_framework = "net10.0", tags = ["manual"], **kwargs)

def action(target, mnemonic):
    matches = [a for a in target[TestingAspectInfo].actions if a.mnemonic == mnemonic]
    if len(matches) != 1:
        fail("Expected one %s action, found %s" % (mnemonic, len(matches)))
    return matches[0]

def request(target, suffix = ".request.json"):
    matches = [a for a in target[TestingAspectInfo].actions if a.mnemonic == "FileWrite" and any([f.basename.endswith(suffix) for f in a.outputs.to_list()])]
    if len(matches) != 1:
        fail("Expected one request: " + suffix)
    return json.decode(matches[0].content)

def paths(files):
    return [f.short_path for f in files.to_list()]

def failure_test(name, target, message):
    analysis_test(name = name, target = target, expect_failure = True, impl = lambda env, subject: env.expect.that_target(subject).failures().contains_predicate(matching.contains(message)))
