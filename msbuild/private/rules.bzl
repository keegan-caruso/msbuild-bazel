"""Assembly, test, generation and restore rule definitions."""

load(":paths.bzl", _NATIVE_TOOLCHAIN = "NATIVE_TOOLCHAIN", _RUNTIME_TOOLCHAIN = "RUNTIME_TOOLCHAIN", _TOOLCHAIN = "TOOLCHAIN")
load(":project.bzl", _project = "build_project")
load(":providers.bzl", "MSBuildAssemblyInfo", "MSBuildBindingInfo", "MSBuildItemsInfo", "MSBuildLayoutInfo", "MSBuildPackageInfo", "MSBuildPackageLockInfo", "MSBuildProjectInfo", "MSBuildProjectOutputInfo", "MSBuildReferencePackInfo", "MSBuildRestoreInfo", "MSBuildRuntimeInfo", "MSBuildToolInfo")
load(":test_options.bzl", _TEST_OPTIONS_ATTRS = "TEST_OPTIONS_ATTRS", _validate_test = "validate_test")

def _library(ctx):
    return _project(ctx)

def _binary(ctx):
    return _project(ctx, executable = True)

def _test(ctx):
    _validate_test(ctx)
    return _project(ctx, executable = ctx.attr.test_protocol != "vstest" or ctx.attr.test_output_type == "exe", test = True)

_ATTRS = {
    "runtime_host": attr.label(providers = [MSBuildRuntimeInfo]),
    "reference_pack": attr.label(providers = [MSBuildReferencePackInfo]),
    "layout_bindings": attr.label_keyed_string_dict(providers = [MSBuildLayoutInfo]),
    "configuration": attr.string(),
    "output_mode": attr.string(default = "sdk", values = ["sdk", "reference", "implementation"]),
    "linux_worker": attr.bool(default = False),
    "allow_remote_execution": attr.bool(default = False),
    "profile_build": attr.bool(default = False),
    "local_native_tools": attr.bool(default = False),
    "native_toolchain": attr.label(allow_single_file = True),
    "use_native_toolchain": attr.bool(default = False),
    "restore": attr.label(providers = [MSBuildRestoreInfo]),
    "prepared_restore": attr.bool(default = False),
    "restore_source_inputs": attr.label_list(allow_files = True),
    "project": attr.label(allow_single_file = [".csproj"], mandatory = True),
    "target_framework": attr.string(mandatory = True),
    "assembly_name": attr.string(),
    "source_paths": attr.label_keyed_string_dict(allow_files = True),
    "srcs": attr.label_list(allow_files = True),
    "directories": attr.string_list(),
    "generated_directories": attr.string_dict(),
    "items": attr.label_list(providers = [MSBuildItemsInfo]),
    "export_targets": attr.string_list_dict(),
    "deps": attr.label_list(providers = [[MSBuildAssemblyInfo], [MSBuildProjectInfo], [MSBuildPackageInfo]]),
    "implementation_deps": attr.label_list(providers = [[MSBuildAssemblyInfo], [MSBuildProjectInfo]]),
    "assembly_selections": attr.label_list(providers = [MSBuildAssemblyInfo]),
    "transitive_compile_references": attr.bool(default = True),
    "tools": attr.label_list(providers = [MSBuildToolInfo], cfg = "exec"),
    "project_outputs": attr.label_list(providers = [MSBuildProjectOutputInfo]),
    "bindings": attr.label_list(providers = [MSBuildBindingInfo], cfg = "exec"),
    "build_deps": attr.label_list(providers = [MSBuildPackageInfo]),
    "package_private_assets": attr.string_dict(),
    "package_lock": attr.label(providers = [MSBuildPackageLockInfo]),
    "analyzers": attr.label_list(providers = [[MSBuildPackageInfo], [MSBuildAssemblyInfo]]),
    "framework_refs": attr.string_list(),
    "framework_assemblies": attr.string_list(),
    "package_reference_paths": attr.string_list_dict(),
    "msbuild_imports": attr.label_list(allow_files = True),
    "import_paths": attr.label_keyed_string_dict(allow_files = True),
    "reference_projects": attr.label_keyed_string_dict(providers = [[MSBuildAssemblyInfo], [MSBuildProjectInfo]]),
    "reference_packages": attr.label_list(providers = [MSBuildPackageInfo]),
    "adapter_imports": attr.label_list(allow_files = [".targets"]),
    "msbuild_properties": attr.string_dict(),
    "defines": attr.string_list(),
    "nullable": attr.string(default = "enable", values = ["enable", "disable", "warnings", "annotations"]),
    "lang_version": attr.string(default = "default"),
    "allow_unsafe": attr.bool(),
    "use_apphost": attr.bool(default = True),
    "data": attr.label_list(allow_files = True),
    "data_paths": attr.label_keyed_string_dict(allow_files = True),
}

msbuild_library = rule(implementation = _library, attrs = _ATTRS, toolchains = [_TOOLCHAIN])
msbuild_binary = rule(implementation = _binary, attrs = _ATTRS, toolchains = [_TOOLCHAIN, config_common.toolchain_type(_RUNTIME_TOOLCHAIN, mandatory = False)], executable = True)
_TEST_ATTRS = dict(_ATTRS, **_TEST_OPTIONS_ATTRS)

msbuild_test = rule(implementation = _test, attrs = _TEST_ATTRS, toolchains = [_TOOLCHAIN, config_common.toolchain_type(_RUNTIME_TOOLCHAIN, mandatory = False)], test = True)

def _generate(ctx):
    if ctx.attr.restore or ctx.attr.export_targets:
        fail("Generation cannot use shared restore or assembly target exports")
    return _project(ctx, executable = ctx.attr.executable, generate = True)

msbuild_generate = rule(
    implementation = _generate,
    attrs = dict(_ATTRS, executable = attr.bool(), targets = attr.string_list(mandatory = True), outputs = attr.string_list(mandatory = True), output_properties = attr.string_dict()),
    toolchains = [_TOOLCHAIN, config_common.toolchain_type(_NATIVE_TOOLCHAIN, mandatory = False)],
)

def _restore(ctx):
    if ctx.attr.export_targets:
        fail("Restore-only rules cannot export build target results")
    project = ctx.actions.declare_file(ctx.label.name + "/BazelRestore.csproj")
    ctx.actions.write(project, '<Project Sdk="Microsoft.NET.Sdk" />')
    return _project(ctx, executable = ctx.attr.executable, restore_only = True, project = project)

_RESTORE_ATTRS = dict(_ATTRS)
_RESTORE_ATTRS.pop("project")
_RESTORE_ATTRS["executable"] = attr.bool()
msbuild_restore = rule(implementation = _restore, attrs = _RESTORE_ATTRS, toolchains = [_TOOLCHAIN])
