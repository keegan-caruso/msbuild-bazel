# Native AOT toolchain closure experiment

The declared Native AOT toolchain initially came from a broad Ubuntu 22.04
ARM64 snapshot: 962 MB extracted and 288 MB compressed. This experiment
removes unused snapshot content while retaining the MSBuild and Native AOT
publish path. It is a qualification artifact, not a distributable toolchain.
The [machine-readable report](native-aot-closure-evidence.json) records the
specific hashes and outcomes.

## Image reference and boundary

Microsoft's [.NET 10 ARM64 AOT SDK image](https://github.com/dotnet/dotnet-docker/blob/main/src/sdk/10.0/noble-aot/arm64v8/Dockerfile)
builds on SDK 10.0.400 and adds `clang`, `llvm`, and `zlib1g-dev`. Its
[Ubuntu Chiseled `runtime-deps` image](https://github.com/dotnet/dotnet-docker/blob/main/src/runtime-deps/10.0/noble-chiseled/arm64v8/Dockerfile)
is a separate *run* image built from Canonical Chisel package slices. It has
the native libraries needed to run an app, but not the SDK, compiler, shell, or
package manager. The [image guidance](https://github.com/dotnet/dotnet-docker/blob/main/documentation/image-variants.md)
uses an AOT SDK for publish and `runtime-deps` for execution. Our Bazel action
similarly needs build tools in its declared inputs; a chiseled runtime image
alone cannot compile the app. We use the package-slice and manifest pattern as
a reference for reducing the toolchain, without claiming that this archive was
produced by Chisel.

## Selection and verification

`tests/explicit_msbuild/native_toolchain_archive.py` is a test-only derivation
from the previous snapshot. It retains selected shell/compiler/linker/symbol
executables; required shared libraries, headers, startup and development
objects; and four `/etc` files. It removes unrelated `/usr/bin` tools, LLVM
static development archives and sanitizer runtimes, CMake, apt, Git and Python
files, GCC's unused compiler backends, and most system static archives. It
omits absolute, escaping and dangling links. It normalizes archive ordering,
owners and timestamps and checks the selected tree's content digest before
packaging. Supplying an expected archive SHA-256 checks the resulting bytes.

The selection is **not** a complete dependency-closure algorithm. It still
retains broad `usr/include` and shared-library directories. The source tree is
captured from installed Ubuntu packages; the script neither downloads pinned
`.deb` inputs nor verifies a package manifest. The selected-tree digest and
archive hash protect this particular run, but cannot by themselves recreate
the snapshot on another machine.

From the Ubuntu 22.04 ARM64 snapshot, with the installed package versions in
the evidence report:

```sh
python3 tests/explicit_msbuild/native_toolchain_archive.py \
  /work/native-aot-declared-qualification-3/source/bazel-bin/native_toolchain.root \
  /work/native-aot-chiseled-v2.tar.gz \
  --expected-tree-sha256 20df32c0e964001454895fe65eb612147008b9d3250e56200ccca8486e131ab4 \
  --expected-archive-sha256 24e80d4625e23aaa6d6592afb064103c649af78fbc040edbe0d5d5c5fdb9d5de
```

The result was 124,907,098 bytes (119.1 MiB); repeating the derivation
produced byte-identical bytes. A wrong selected-tree hash and a wrong expected
archive hash both failed without retaining an output file. The archive is
smaller than the broad 288 MB qualification archive. During trimming, removing
`libm.a` caused `ld.bfd: cannot find -lm`; restoring it made the fixture pass.
This is why the selection retains that static archive.

The full Linux ARM64 Native AOT fixture used the compact archive as the Bazel
`native_toolchain` input. It built and ran the initial app, rebuilt after a body
edit, rejected a missing ILCompiler package, and rejected a wrong toolchain
archive hash. The body-edited ARM64 ELF printed `NATIVE_AOT_EDIT` and had
SHA-256 `fdc5e951b39daff06910fdc4568cf2edd4c11d5d11b09246478795a477ce3f8a`.
The same fixture then passed a fresh build in a second Apple Container without
ambient `clang` or `gcc`: Bazel reported eight Linux-sandbox actions and one
local `MSBuildGenerate` action, with the same initial and body-edit binary
hashes. No remote cache was configured for that run. This shows the smaller
archive supplies the native tools needed by this fixture even on a
compiler-free host.
The same binary ran in the official `runtime-deps:10.0-noble-chiseled` ARM64
image (platform manifest digest
`sha256:ffc68ca606d9876046bab910d4b056113b233fa2637904ae29a187d839ce049f`).
This checks one executable in that run environment; it does not prove all AOT
apps have the same runtime dependency closure.

## Next boundary

Replace the installed-package snapshot with pinned distro package payloads
and a reviewed manifest of retained files and their license notices. Then
declare the platform/architecture and version as a Bazel toolchain and test
execution in an independent worker. This qualification does not establish
remote execution or portability beyond the measured Linux ARM64 image pair.
