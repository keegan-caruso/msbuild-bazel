# Compatible frameworks and dual-role tools

Compile dependencies select exactly one configured Bazel label per project.
The runner checks each direct edge using the pinned SDK's NuGet.Frameworks
compatibility provider before project preparation. It does not discover or select
another target framework. Unsupported frameworks and incompatible edges fail.
Existing transitive reference/runtime/package propagation remains unchanged.

A project can now be both a compile dependency (`deps`) and a build tool (`tools`).
Its original ProjectReference must retain ordinary compile semantics. Build-only
tool edges still require ReferenceOutputAssembly=false. Tool/analyzer overlap and
compile/analyzer overlap remain unsupported. Execution-configured tool outputs
and target-configured compilation outputs remain separate Bazel dependencies.

The mixed-role mode of `tests/explicit_msbuild/tool_bindings.py <fresh-dir>
--mixed-roles` checks a netstandard2.1 helper, a net10.0 task, and a consumer that
both executes the task and calls the helper at runtime. NETStandard.Library.Ref
2.1.0 is a SHA-256 pinned package input. Eleven cases passed on Ubuntu 22.04 ARM64,
SDK 10.0.400 and Bazel 9.2.0, including an incompatible-framework rejection,
implementation-edit invalidation with unchanged reference bytes, role and binding
rejections, and all five configured assembly actions hitting disk cache after
relocation and deletion of the first producer workspace/output base.
