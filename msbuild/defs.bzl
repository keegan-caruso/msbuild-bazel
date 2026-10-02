"""Public API for declared MSBuild graphs, artifacts and executable tests."""

load("//msbuild:graph.bzl", _msbuild_graph = "msbuild_graph", _msbuild_graph_binary = "msbuild_graph_binary", _msbuild_graph_layout = "msbuild_graph_layout", _msbuild_graph_output = "msbuild_graph_output", _msbuild_graph_restore = "msbuild_graph_restore", _msbuild_graph_runner = "msbuild_graph_runner", _msbuild_graph_test = "msbuild_graph_test")
load("//msbuild/private:inputs.bzl", _msbuild_file_binding = "msbuild_file_binding", _msbuild_tool = "msbuild_tool")
load("//msbuild/private:layouts.bzl", _msbuild_layout = "msbuild_layout", _msbuild_native_tool = "msbuild_native_tool", _msbuild_runtime = "msbuild_runtime")
load("//msbuild/private:native_toolchain.bzl", _msbuild_native_toolchain = "msbuild_native_toolchain", _msbuild_native_toolchain_archive = "msbuild_native_toolchain_archive", _msbuild_native_toolchain_packages = "msbuild_native_toolchain_packages")
load("//msbuild/private:packages.bzl", _msbuild_generated_nuget_package = "msbuild_generated_nuget_package", _msbuild_nuget_dependencies = "msbuild_nuget_dependencies", _msbuild_nuget_package = "msbuild_nuget_package", _msbuild_package_lock = "msbuild_package_lock")
load("//msbuild/private:providers.bzl", _MSBuildBindingInfo = "MSBuildBindingInfo", _MSBuildLayoutInfo = "MSBuildLayoutInfo", _MSBuildPackageInfo = "MSBuildPackageInfo", _MSBuildPackageLockInfo = "MSBuildPackageLockInfo", _MSBuildRuntimeInfo = "MSBuildRuntimeInfo", _MSBuildTestToolInfo = "MSBuildTestToolInfo", _MSBuildToolInfo = "MSBuildToolInfo")
load("//msbuild/private:test_tools.bzl", _msbuild_test_tool = "msbuild_test_tool")

MSBuildBindingInfo = _MSBuildBindingInfo
MSBuildLayoutInfo = _MSBuildLayoutInfo
MSBuildPackageInfo = _MSBuildPackageInfo
MSBuildPackageLockInfo = _MSBuildPackageLockInfo
MSBuildRuntimeInfo = _MSBuildRuntimeInfo
MSBuildTestToolInfo = _MSBuildTestToolInfo
MSBuildToolInfo = _MSBuildToolInfo
msbuild_file_binding = _msbuild_file_binding
msbuild_generated_nuget_package = _msbuild_generated_nuget_package
msbuild_layout = _msbuild_layout
msbuild_native_tool = _msbuild_native_tool
msbuild_native_toolchain = _msbuild_native_toolchain
msbuild_native_toolchain_archive = _msbuild_native_toolchain_archive
msbuild_native_toolchain_packages = _msbuild_native_toolchain_packages
msbuild_nuget_dependencies = _msbuild_nuget_dependencies
msbuild_nuget_package = _msbuild_nuget_package
msbuild_package_lock = _msbuild_package_lock
msbuild_runtime = _msbuild_runtime
msbuild_test_tool = _msbuild_test_tool
msbuild_tool = _msbuild_tool

msbuild_graph = _msbuild_graph
msbuild_graph_restore = _msbuild_graph_restore
msbuild_graph_runner = _msbuild_graph_runner
msbuild_graph_test = _msbuild_graph_test

msbuild_graph_binary = _msbuild_graph_binary

msbuild_graph_layout = _msbuild_graph_layout

msbuild_graph_output = _msbuild_graph_output
