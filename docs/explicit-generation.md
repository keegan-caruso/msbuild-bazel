# Explicit MSBuild generation

`msbuild_generate` runs declared targets after offline restore, without requiring
an assembly build. It accepts the same explicit input/package/tool declarations as
assembly rules. Outputs are individual Bazel file artifacts, not an opaque tree.

```python
msbuild_generate(
    name = "interop",
    project = "Generate.csproj",
    target_framework = "net10.0",
    targets = ["GenerateMicroComItems"],
    outputs = ["Interop.Generated.cs"],
    output_properties = {"GeneratedSource": "Interop.Generated.cs"},
    items = [":idl"],
    build_deps = [":microcom"],
    package_private_assets = {"MicroCom.CodeGenerator.MSBuild": "all"},
    adapter_imports = ["microcom.targets"],
    linux_worker = True,
)
```

An output property binds to the corresponding file in writable action state.
Parents are created before evaluation. Conflicting/reserved properties, unsafe
relative paths, overridden bindings, absent outputs and symlink outputs fail.
Sources stay read-only. Adapters may use the bound property to update task item
metadata before generation. They do not change the generator implementation.

The default output set contains every declared generated file. For one output,
use the target directly in `srcs`; for multiple outputs, select a named output
with a filegroup's `output_group` (the declared relative output path). Shared
restore and assembly target-result exports are intentionally unavailable for this
initial generator rule. Generation uses the `MSBuildGenerate` mnemonic; select
its worker strategy explicitly just as for `MSBuildAssembly`.

## Avalonia evidence

`tests/explicit_msbuild/avalonia_generation.py <fresh-dir> <Avalonia-checkout>`
checks revision `37fbd9655cc581ff5b1c6b1fb1be4e3118c889d0` (11.3.12), pins
MicroCom.CodeGenerator.MSBuild 0.11.0 by archive SHA-256 and calls its real targets.
A small explicit driver project supplies each unmodified upstream IDL. This is a
generator integration, not a build of Avalonia's original assembly projects.

All five files (Native, Win32Com, WinRT, DirectX and DComposition) produced exact
raw-MSBuild byte parity on Ubuntu 22.04 ARM64 / SDK 10.0.400 / Bazel 9.2.0.
Source-write and absent-output negative controls passed. After removing the raw
producer and first output base, a relocated workspace/fresh user root recovered
the action from disk cache. [Results](avalonia-generation-evidence.json).

Subsequent [Simple theme graph qualification](avalonia-xaml-subset.md) covers
actual project compilation and XAML rewriting, with [HTTP cache recovery across
containers](avalonia-http-cache.md). Full Avalonia/platform-backend coverage
remains unqualified. No package-specific branch was added to the runner.
