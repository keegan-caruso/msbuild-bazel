# Native x64 NativeAOT consumer

`../native_aot_x64.py` publishes a small `net10.0` application through the public graph rules using a verified source-built SDK **10.0.100**, its bundled AOT packs, and declared **Clang/LLD 18.1.8** tools. Run on native Ubuntu 26.04 x64 with Python 3.11+, the pinned Bazelisk, nested namespaces, and permitted `/usr/bin/bwrap`. Acquire or produce inputs before this bounded consumer job; no upstream source build runs here.

```sh
python3 tests/source_sdk/native_aot_x64.py /build/fresh-aot \
  --sdk "$SDK_ARCHIVE" --sdk-sha256 "$SDK_SHA256" \
  --native "$NATIVE_ARCHIVE" --native-sha256 "$NATIVE_SHA256"
```

Produce the native archive with `scripts/assemble-native-toolchain.py --architecture=x64 --sdk`; retain its receipt. SDK production and its source pins are described in [the x64 recipe](../LINUX_X64.md). The fixture uses the SDK's distro RID `ubuntu.26.04-x64`; it does not acquire substitute AOT packs. It copies verified archives into the disposable workspace and registers the SDK as a declared Bazel artifact.

The 900-second Bazel deadline covers graph Publish and exported layout. The driver checks actual Clang/LLD version output, ELF machine 62, absence of managed-host companions, and an application guard rejecting dynamic-code support. It packages the layout, extracts it, and runs the lone ELF from an otherwise empty directory with a nonexistent `DOTNET_ROOT` and a 30-second deadline. `report.json` records archive and ELF identities, the exact command, and output. Keep `publish.log`, `execution.json`, `inputs.json`, and `published.tar.gz` with the report.

This is a native x64 source-SDK/AOT consumer control. It does not qualify older glibc deployment, cross-host cache recovery, RBE, signing, or whole upstream parity. The full LLVM closure is an input; ordinary graph sandboxing still exposes host `/usr`, as documented in [support](../../../docs/support.md).
