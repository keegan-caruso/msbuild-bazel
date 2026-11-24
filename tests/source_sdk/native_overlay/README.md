# Source SDK native prerequisite overlay

Qualification-only overlay adding Ubuntu 26.04 ARM64/AMD64 source-SDK prerequisites to a locally built `containers/runtime-demo.Dockerfile` image (not a published image; does not install/build an SDK). Identify the base by immutable digest. Base Dockerfile pins the Ubuntu index and LLVM/Clang 18; other base APT packages resolve at image-build time.

Apple Container (from repo root):

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

[ARM64](packages.json) and [AMD64](packages-amd64.json) manifests pin exact overlay archives, versions, architectures, and SHA256s. The installer fetches each version via authenticated APT metadata, verifies bytes and Debian identity, installs offline from a private APT cache of verified archives only, and rejects unlisted additions or removals. Base ref, manifest, and `installed.tsv` are saved under `/opt/source-sdk-prerequisites/`. Missing pinned archives or extra base dependencies fail the build (retain an authenticated package snapshot for long-term reproduction).

Capture and test the native tool root in the same nested boundary as the source build (fresh evidence dir with free space; never mount a rules checkout under the evidence dir—overlapping mounts can hide it):

```sh
mkdir /path/to/fresh-evidence
container run --rm --arch arm64 --cpus 2 --memory 4G \
  --cap-add SYS_ADMIN --masked-path NONE --read-only-path NONE \
  --volume "$PWD:/rules:ro" --volume /path/to/fresh-evidence:/proof \
  source-sdk-native-overlay python3 /rules/tests/source_sdk/native_overlay/preflight.py
```

Outer flags allow the nested sandbox; inner Bubblewrap is read-only with dropped capabilities, unshared network, and cleared env. Probes `file`, `cpio`, Python, LLDB 18, dependency resolution, and Brotli compile/link/run with Clang 18; emits native archive hash and installed inventory.

Against the recorded base, sealed preflight reproduced the prior Ubuntu 26 / LLVM 18 root SHA256 `1854d067717cba3afe85c01e166e2a2c7d95c4dafea89e172b69da8b536c874a` (used by the source producer to build SDK 10.0.100 SHA256 `e043c131f157a4dfd8f66bfe6016b95ee301d0265b075a69b5c84dd9577c45a2`) without repeating the SDK build. Newly resolved bases are not guaranteed byte-identical; historical Ubuntu 22 results keep their original scope; preflight does not produce an SDK.

For native Linux x64, build base and overlay on Ubuntu 26.04 x64 via `docker build --platform linux/amd64` with immutable `NATIVE_BASE`. Installer selects the AMD64 catalog from Debian arch and rejects foreign architectures. AMD64 hashes were verified against downloaded Ubuntu bytes (recipe preparation only, not a qualified x64 image/build); the 17 shared overlay versions match ARM64 plus `libipt2` (LLDB Intel PT dep). Sealed root keeps `/lib64` for the x64 ELF loader; run `preflight.py` with Bubblewrap before building. Base APT closure still needs its own captured inventory and root hash.

See [x64 producer recipe](../LINUX_X64.md) for x64 acquisition/producer commands; ARM64 component scheduling remains separate.
