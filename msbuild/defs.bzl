"""Public API for explicit MSBuild projects, inputs and executable tests."""

load("//msbuild/private:assembly.bzl", _msbuild_assembly = "msbuild_assembly")
load("//msbuild/private:inputs.bzl", _msbuild_file_binding = "msbuild_file_binding", _msbuild_items = "msbuild_items", _msbuild_project_output = "msbuild_project_output", _msbuild_target_items = "msbuild_target_items", _msbuild_tool = "msbuild_tool")
load("//msbuild/private:layouts.bzl", _msbuild_layout = "msbuild_layout", _msbuild_native_tool = "msbuild_native_tool", _msbuild_reference_pack = "msbuild_reference_pack", _msbuild_runtime = "msbuild_runtime")
load("//msbuild/private:packages.bzl", _msbuild_nuget_dependencies = "msbuild_nuget_dependencies", _msbuild_nuget_package = "msbuild_nuget_package", _msbuild_package_lock = "msbuild_package_lock")
load("//msbuild/private:providers.bzl", _MSBuildAssemblyInfo = "MSBuildAssemblyInfo", _MSBuildBindingInfo = "MSBuildBindingInfo", _MSBuildItemsInfo = "MSBuildItemsInfo", _MSBuildLayoutInfo = "MSBuildLayoutInfo", _MSBuildPackageInfo = "MSBuildPackageInfo", _MSBuildPackageLockInfo = "MSBuildPackageLockInfo", _MSBuildProjectOutputInfo = "MSBuildProjectOutputInfo", _MSBuildReferencePackInfo = "MSBuildReferencePackInfo", _MSBuildRestoreInfo = "MSBuildRestoreInfo", _MSBuildRuntimeInfo = "MSBuildRuntimeInfo", _MSBuildTestToolInfo = "MSBuildTestToolInfo", _MSBuildToolInfo = "MSBuildToolInfo")
load("//msbuild/private:rules.bzl", _msbuild_binary = "msbuild_binary", _msbuild_generate = "msbuild_generate", _msbuild_library = "msbuild_library", _msbuild_restore = "msbuild_restore", _msbuild_test = "msbuild_test")
load("//msbuild/private:test_tools.bzl", _msbuild_test_tool = "msbuild_test_tool")

MSBuildAssemblyInfo = _MSBuildAssemblyInfo
MSBuildBindingInfo = _MSBuildBindingInfo
MSBuildItemsInfo = _MSBuildItemsInfo
MSBuildLayoutInfo = _MSBuildLayoutInfo
MSBuildPackageInfo = _MSBuildPackageInfo
MSBuildPackageLockInfo = _MSBuildPackageLockInfo
MSBuildProjectOutputInfo = _MSBuildProjectOutputInfo
MSBuildReferencePackInfo = _MSBuildReferencePackInfo
MSBuildRestoreInfo = _MSBuildRestoreInfo
MSBuildRuntimeInfo = _MSBuildRuntimeInfo
MSBuildTestToolInfo = _MSBuildTestToolInfo
MSBuildToolInfo = _MSBuildToolInfo
msbuild_assembly = _msbuild_assembly
msbuild_binary = _msbuild_binary
msbuild_file_binding = _msbuild_file_binding
msbuild_generate = _msbuild_generate
msbuild_items = _msbuild_items
msbuild_layout = _msbuild_layout
msbuild_library = _msbuild_library
msbuild_native_tool = _msbuild_native_tool
msbuild_nuget_dependencies = _msbuild_nuget_dependencies
msbuild_nuget_package = _msbuild_nuget_package
msbuild_package_lock = _msbuild_package_lock
msbuild_project_output = _msbuild_project_output
msbuild_reference_pack = _msbuild_reference_pack
msbuild_restore = _msbuild_restore
msbuild_runtime = _msbuild_runtime
msbuild_target_items = _msbuild_target_items
msbuild_test = _msbuild_test
msbuild_test_tool = _msbuild_test_tool
msbuild_tool = _msbuild_tool
