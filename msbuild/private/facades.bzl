"""Convenient declarations that expand into explicit framework targets."""

load(":rules.bzl", "msbuild_library", "msbuild_test")
load(":variants.bzl", "project_group")

_LIST_ATTRIBUTES = [
    "srcs",
    "deps",
    "items",
    "analyzers",
    "tools",
    "bindings",
    "build_deps",
    "project_outputs",
    "framework_refs",
    "framework_assemblies",
    "msbuild_imports",
    "reference_packages",
    "adapter_imports",
    "defines",
    "directories",
    "data",
    "test_adapters",
    "test_output_dirs",
    "args",
    "tags",
    "features",
    "compatible_with",
    "restricted_to",
    "exec_compatible_with",
    "target_compatible_with",
]

def _variants(name, project, target_frameworks, framework_overrides, rule_impl, kwargs):
    if type(target_frameworks) != "list" or not target_frameworks:
        fail("target_frameworks must be a nonempty literal list")
    if "target_framework" in kwargs:
        fail("Use target_frameworks with the project facade")
    if len(target_frameworks) != len({tfm: True for tfm in target_frameworks}):
        fail("Duplicate target_frameworks")
    for tfm in framework_overrides:
        if tfm not in target_frameworks:
            fail("framework_overrides contains an undeclared framework: " + tfm)
    names = []
    for tfm in target_frameworks:
        if type(tfm) != "string" or not tfm or any([c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in tfm.elems()]):
            fail("Frameworks must be lowercase TFMs: " + str(tfm))
        variant = name + "_" + tfm.replace(".", "_")
        attrs = dict(kwargs)
        for key, value in framework_overrides.get(tfm, {}).items():
            if key in ["name", "project", "target_framework", "target_frameworks", "visibility", "testonly"]:
                fail("framework_overrides cannot change " + key)
            attrs[key] = attrs.get(key, []) + value if key in _LIST_ATTRIBUTES else value
        rule_impl(name = variant, project = project, target_framework = tfm, **attrs)
        names.append(":" + variant)
    return names

def msbuild_project(name, project, target_frameworks, framework_overrides = {}, **kwargs):
    """Declare library variants and a selectable aggregate facade.

    Args:
        name: Aggregate name; variants are name_TFM with dots replaced by underscores.
        project: Shared SDK-style csproj file.
        target_frameworks: Nonempty literal list of distinct target frameworks.
        framework_overrides: Per-framework attributes; lists extend, other values replace.
        **kwargs: Common msbuild_library attributes, including configurable values.
    """
    variants = _variants(name, project, target_frameworks, framework_overrides, msbuild_library, kwargs)
    project_group(name = name, variants = variants, **{k: kwargs[k] for k in ["visibility", "testonly", "tags"] if k in kwargs})

def msbuild_test_project(name, project, target_frameworks, framework_overrides = {}, **kwargs):
    """Declare framework-specific tests and a test_suite aggregating them.

    Args:
        name: Test suite name; individual variants use the same naming as msbuild_project.
        project: Shared SDK-style test csproj file.
        target_frameworks: Nonempty literal list of distinct target frameworks.
        framework_overrides: Per-framework attributes; lists extend, other values replace.
        **kwargs: Common msbuild_test attributes, including runner and adapters.
    """
    variants = _variants(name, project, target_frameworks, framework_overrides, msbuild_test, kwargs)
    native.test_suite(name = name, tests = variants, **{k: kwargs[k] for k in ["visibility", "testonly", "tags"] if k in kwargs})
