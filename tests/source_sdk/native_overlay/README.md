# Source SDK native prerequisite overlay

This qualification-only overlay adds the recorded Ubuntu 26.04 ARM64 or AMD64
source-SDK prerequisites to a locally built runtime native image. It is not a
published image and does not install an SDK or build one. Build the base from
`containers/runtime-demo.Dockerfile`, then identify that local image by its
immutable digest. The base Dockerfile pins the Ubuntu index and LLVM/Clang 18;
other base APT packages remain resolved at image-build time.

For Apple Container, from the repository root:

```sh
base_context="$(mktemp -d)"
cp containers/runtime-demo.Dockerfile "$base_context/Dockerfile"
container build --platform linux/arm64 --cpus 4 --memory 4G \
  --tag source-sdk-native-base "$base_context"
rm "$base_context/Dockerfile"
rmdir "$base_context"
# Set NATIVE_BASE to the local image name followed by @sha256:<inspected digest>.
container image inspect source-sdk-native-base
# Register the local digest alias so Apple Container does not look it up remotely.
container image tag source-sdk-native-base "$NATIVE_BASE"
container build --platform linux/arm64 --cpus 2 --memory 4G \
  --build-arg "NATIVE_BASE=$NATIVE_BASE" --tag source-sdk-native-overlay \
  tests/source_sdk/native_overlay
```

The [ARM64 manifest](packages.json) and [AMD64 manifest](packages-amd64.json) record the exact overlay archives, versions,
architectures and SHA256 values from the qualified build. The installer obtains
each exact version using authenticated APT metadata, checks its bytes and Debian
identity before installation, and rejects an install transaction that requires
unlisted packages or removes a package. Installation has no downloads and uses
a private APT cache containing only the verified archives. The immutable base
reference, manifest and complete installed inventory are saved under
`/opt/source-sdk-prerequisites/`; the inventory is `installed.tsv`. If a pinned
archive is no longer available, or a different base needs additional packages,
the build fails;
retain an authenticated package snapshot for long-term reproduction.

To capture the native tool root and test it inside the same nested boundary as
the source build, use a fresh host evidence directory with sufficient free space:

```sh
mkdir /path/to/fresh-evidence
container run --rm --arch arm64 --cpus 2 --memory 4G \
  --cap-add SYS_ADMIN --masked-path NONE --read-only-path NONE \
  --volume "$PWD:/rules:ro" --volume /path/to/fresh-evidence:/proof \
  source-sdk-native-overlay python3 /rules/tests/source_sdk/native_overlay/preflight.py
```

The outer capability and mount settings permit the nested sandbox; the inner
Bubblewrap root is read-only with all capabilities dropped, network unshared and
environment cleared. The probe tests `file`, cpio, Python, LLDB18, dependency
resolution, and Brotli compilation/link/execution with Clang 18. It emits a
native archive hash and installed inventory. Do not mount a rules checkout under
the evidence directory: overlapping host mounts can hide the latter.

A prior captured root from Ubuntu 26 / LLVM 18 had SHA256
`1854d067717cba3afe85c01e166e2a2c7d95c4dafea89e172b69da8b536c874a`;
the current recipe was built against the recorded base and its sealed preflight
reproduced that same root hash without repeating the SDK build. The declared
source-SDK producer used the root and produced SDK 10.0.100
archive SHA256 `e043c131f157a4dfd8f66bfe6016b95ee301d0265b075a69b5c84dd9577c45a2`.
These identify the recorded run, not a promise that a newly resolved base will
produce identical bytes. Historical Ubuntu 22 SDK results retain their original
scope. The preflight checks prerequisites; it does not itself produce an SDK.

For a native Linux x64 producer, build the same base and overlay with Docker on
Ubuntu 26.04 x64. Use `docker build --platform linux/amd64` for both builds and
pass an immutable `NATIVE_BASE` as above. The installer selects the AMD64 catalog
from the actual Debian architecture and rejects foreign package architectures.
The AMD64 archive hashes were checked against downloaded Ubuntu archive bytes;
this prepares a recipe, and does not qualify a completed x64 image or source build.
The sealed root includes `/lib64` when present so the x64 ELF loader remains
available. Run `preflight.py` inside the fresh x64 image with Bubblewrap permitted
before starting the source build. The 17 shared overlay versions match ARM64
exactly; AMD64 also pins LLDB's Intel Processor Trace dependency `libipt2`.
The base APT closure still needs its own captured inventory and native-root hash.

Native x64 source-SDK acquisition and producer commands are documented in
[the x64 producer recipe](../LINUX_X64.md). ARM64 component scheduling experiments
remain a separate scope.
