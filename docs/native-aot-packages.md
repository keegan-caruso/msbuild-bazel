# Native AOT toolchain from locked Ubuntu packages

The Linux ARM64 Native AOT fixture assembles its compiler and sysroot from
34 Ubuntu 22.04 `.deb` packages pinned by SHA-256. The
[package lock](../tests/explicit_msbuild/native_aot_packages.lock.json) names
each exact version, architecture, source URL, SHA-256 and copyright path. The
[retained-file manifest](../tests/explicit_msbuild/native_aot_files.manifest)
lists 3,094 files and links. These two files replace the dependency on a
snapshot of *installed* compiler packages. Ubuntu's [package guidance](https://ubuntu.com/project/docs/how-ubuntu-is-made/concepts/debian-directory/)
places each package's license and copyright notice under
`usr/share/doc/<package>/copyright`; the assembler requires every locked
notice to resolve in the output tree.

`msbuild_native_toolchain_packages` is a Bazel rule that takes the `.deb` files,
their expected hashes and the manifest as declared inputs, then emits the
`native_toolchain` tree artifact consumed by `msbuild_generate`. Its .NET
runner verifies every package hash, asks `dpkg-deb` for the uncompressed file
tar stream, copies only manifest-listed entries, preserves modes, rewrites
rooted package links to relative links under the tree and rejects missing or
escaping links. It does not install packages or run maintainer scripts. The
action is local-only because `/usr/bin/dpkg-deb` is still supplied by the
qualified Ubuntu build image rather than a declared Bazel tool. The produced
tree remains an explicit input to the AOT action.

The fixture fetches and checks the locked inputs with:

```sh
python3 tests/explicit_msbuild/download_native_aot_packages.py /work/native-aot-debs
```

On Ubuntu 22.04 ARM64 with SDK 10.0.400 and Bazel 9.2.0, the qualification
used the already verified package directory and an isolated Bazel output base:

```sh
python3 tests/explicit_msbuild/native_aot.py /work/aot-package-rule-qual3 \
  --package-cache /work/native-aot-cache \
  --native-package-directory /work/native-aot-debs
```

This built and ran the initial and body-edited Native AOT app. The binary
SHA-256 values were `2024acd2d33735eb83a9f6e11b0cec10d28966d614572098478712327ff34c79`
and `f0cdfbad3bf96be3a13fd3cfb64b944117e33b1cc942a4ba35e94817d4eb3e7f`,
the same as the earlier declared-tree run. Omitting ILCompiler failed closed;
changing one expected `.deb` SHA-256 made package assembly fail. The selected
tree contained 3,094 manifest entries and occupied 276 MB on disk. The 34
verified package archives occupied 75 MB. A separate test-only tar derivation
from those same packages was 80,366,854 bytes and also passed the fixture.
These are correctness observations, not build-time benchmarks. The
[evidence report](native-aot-packages-evidence.json) records the hashes and
controls.

The source URLs are mutable Ubuntu archive locations; the locked SHA-256 values
fail closed if their bytes change or disappear. Package assembly still relies
on the local Ubuntu `dpkg-deb` implementation, so it is not yet a remotely
executable Bazel action. This package-assembly qualification covers Ubuntu
22.04 ARM64 and one AOT project; it does not establish a minimal compiler
closure, cross-platform toolchain or source-built NativeAOT. Remote generation
is qualified below.

## Fresh compiler-free consumer

The committed repository tree was copied into a new Ubuntu 22.04 ARM64 Apple
container based on the pinned toolchain image. That container had SDK 10.0.400,
Bazel 9.2.0 and `dpkg-deb`, but `command -v` found no `clang`, `gcc`, `ld`, `as`
or `llvm-objcopy`. The 34 locked `.deb` files and isolated NuGet package cache
were copied into it separately. With a new workspace and Bazel output base,
the following fixture passed:

```sh
python3 tests/explicit_msbuild/native_aot.py /work/aot-package-clean \
  --package-cache /work/native-aot-cache \
  --native-package-directory /work/native-aot-debs
```

The initial executable hash was
`2024acd2d33735eb83a9f6e11b0cec10d28966d614572098478712327ff34c79`;
after a body edit it was
`f0cdfbad3bf96be3a13fd3cfb64b944117e33b1cc942a4ba35e94817d4eb3e7f`.
The fixture ran both executables and rejected missing ILCompiler and a wrong
`.deb` hash. These hashes match the producer run above. The consumer used only
the pinned SDK, Bazel, `dpkg-deb` and declared package payloads for the native
compiler and linker inputs. This validates a fresh local build; it does not
establish remote execution, because package assembly still uses an ambient
`dpkg-deb`.

## Bazel selection and remote execution

An app can bind the package-built tree to Bazel's native toolchain type and
register it for a compatible execution and target platform. `msbuild_generate`
then selects that binding with `use_native_toolchain = True`; it fails analysis
if no matching toolchain is registered. The explicit `native_toolchain` label
remains available for a directly chosen tree.

```starlark
msbuild_native_toolchain_packages(
    name = "native_packages",
    manifest = "native-aot-files.manifest",
    packages = {
        "packages/libc6-dev.deb": "<locked SHA-256>",
        # Include the other 33 locked package archives.
    },
)
msbuild_native_toolchain(name = "native_binding", root = ":native_packages")
toolchain(
    name = "native_registered",
    toolchain = ":native_binding",
    toolchain_type = "@rules_msbuild//msbuild:native_toolchain_type",
    exec_compatible_with = ["@platforms//os:linux", "@platforms//cpu:aarch64"],
    target_compatible_with = ["@platforms//os:linux", "@platforms//cpu:aarch64"],
)
msbuild_generate(
    name = "aot",
    # Project, sources, locked NuGet packages, targets and outputs as above.
    use_native_toolchain = True,
    allow_remote_execution = True,
)
```

Register `//:native_registered` in `MODULE.bazel` with
`register_toolchains("//:native_registered")`. The
[acceptance fixture](../tests/explicit_msbuild/native_aot.py) writes a complete
BUILD declaration with the locked package hashes.

On the same Ubuntu 22.04 ARM64 client, the selected-toolchain fixture passed
with no installed native compiler, including the initial build, body edit,
missing ILCompiler, bad `.deb` hash and missing-registration controls. The
client then ran it against the pinned [Buildbarn fixture](remote-execution.md#reproduce-with-buildbarn)
with the worker's installed SDK removed and no installed compiler or linker:

```sh
python3 tests/explicit_msbuild/native_aot.py /work/aot-selected-remote-final \
  --package-cache /work/native-aot-cache \
  --native-package-directory /work/native-aot-debs \
  --selected-native-toolchain \
  --remote-executor grpc://WORKER_IP:8980
```

Local fallback and remote action-cache reads were disabled. Bazel's initial
execution log recorded one remote SDK-runner bootstrap, six remote NuGet
extractions, one **local** native package assembly, and one remote
`MSBuildGenerate`. A body edit ran one new remote `MSBuildGenerate`. Both
binaries ran on the client and had the same hashes as the local runs above.
Removing the toolchain registration failed analysis; removing ILCompiler and
changing a `.deb` hash also failed closed. The stream reader now drains
`dpkg-deb`'s remaining tar padding before closing its output pipe; the remote
qualification exposed an intermittent broken-pipe failure without that drain.
The [evidence JSON](native-aot-packages-evidence.json) summarizes the results.

Package assembly remains a local action because it invokes the build image's
`/usr/bin/dpkg-deb`. The remote fixture explicitly selects its local strategy
while forcing generation remote. This establishes remote execution for one
Linux ARM64 Native AOT app, not remote execution of package assembly, other
architectures or a complete application graph.
