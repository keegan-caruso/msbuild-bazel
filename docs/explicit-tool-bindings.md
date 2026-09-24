# Explicit MSBuild task tools

The first implementation of the [build-input design (historical)](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/explicit-build-input-design.md)
adds a build-only project role and task property bindings. It does not introduce
NBGV, Avalonia or Arcade names into the runner.

```python
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_tool", "msbuild_file_binding", "msbuild_library")

msbuild_tool(name = "task_tool", assembly = ":Tasks")
msbuild_file_binding(
    name = "task_location",
    tool = ":task_tool",
    property_name = "BuildTasksLocation",
)
msbuild_library(
    name = "Consumer",
    project = "Consumer.csproj",
    target_framework = "net10.0",
    srcs = ["Consumer.cs"],
    tools = [":task_tool"],
    bindings = [":task_location"],
    linux_worker = True,
)
```

`msbuild_tool.assembly` selects an assembly producer in the execution
configuration. `entry_point` defaults to its DLL name and can select a safe
relative file inside the staged implementation closure. The closure includes
transitive runtime directories and runtime data. It is staged read-only under
`.build-tools/<index>` independently of compiler references, analyzers, or the
application's runtime delivery.

`layout_prefix = "net"` stages that entire closure under
`.build-tools/<index>/net` and prefixes the bound entry point accordingly. This
preserves tools that locate adjacent files relative to their own assembly. The
prefix defaults to empty and must be a safe relative directory. It does not
change compile or application-runtime dependencies.

Each binding must name a tool also listed in `tools`. A property is installed as
a global property before evaluation; its path comes from the declared artifact.
Reserved runner/MSBuild/restore properties, collisions with scalar properties,
duplicate bindings, absent entries and unsafe entry paths are rejected. A project
that makes the property local and overwrites it is rejected before restore.

An upstream ProjectReference to a declared tool must be build-only:
`ReferenceOutputAssembly=false` with no OutputItemType. Tools need not have a
ProjectReference when consumed directly by UsingTask. Existing compile/analyzer
edges retain their exact declaration checks. A tool may also be an explicitly
declared compile dependency; that edge must retain normal compile semantics.
[Compatible framework and dual-role controls](framework-tool-roles.md) cover this
case. Tool/analyzer overlap remains unsupported. External executable launchers
remain follow-up work; [generator actions](explicit-generation.md) provide
writable output property bindings.

The property binding permits an ordinary UsingTask declaration to find the task
without borrowing a producer's bin directory. Tool implementation changes
participate in the consumer action identity, including helper DLL changes whose
reference assemblies remain unchanged. Task DLLs do not become application runtime
dependencies merely because the task executes during compilation.

## Validation

Run `tests/explicit_msbuild/tool_bindings.py` in the qualified Ubuntu ARM64 worker
environment with `RULES_MSBUILD_BAZEL` and `RULES_MSBUILD_REPOSITORY_CACHE` set. The
fixture compiles and executes an actual ITask with a separately compiled helper,
generates a source file in the consumer's intermediate directory, and checks that
a helper body edit changes output while reference DLLs remain stable. It exercises
invalid role/property/tool/entry bindings and deleted-producer cache recovery.

The Linux worker run passed all ten cases, including all three assembly actions
hitting the disk action cache after deleting the producer checkout and output base.
The helper-body edit executed exactly Helper and App, leaving Tasks cached. This
proves independent local-cache recovery; HTTP remote recovery is not claimed for
this fixture. Existing worker acceptance, .NET builds/formatting, 24 owned test
checks (5 style, 6 tooling, 13 explicit), and toolchain/Starlark checks passed.
[Case results](explicit-tool-bindings-evidence.json).
