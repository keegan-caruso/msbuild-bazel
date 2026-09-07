# Explicit discovered Nix SDK import inputs

Graph input paths `nix/<store-name>[/relative-path]` identify discovered imported
files under `/nix/store`, only for an SDK located in that store. Preparation
accepts this root solely for `kind=import`, validates the store name and relative
path, requires the resolved file to remain in the store, and verifies the manifest
hash using the existing import normalization. Other input kinds, non-Nix SDKs and
unsafe paths fail before publication.

Preparation passes the sorted unique absolute paths as `external_imports` to
`local_dotnet_sdk`. That repository attribute defaults to an empty list, preserving
other SDK setups. Each file is linked at `imports/<index>` and included in the SDK
filegroup, making the actual file bytes part of each action's declared SDK inputs.
This covers the pinned SDK's `extra.targets` and `sign-apphost.proj` imports outside
its SDK directory. Builds still read their immutable original Nix locations; this
is explicit input hashing, not filesystem relocation or full host/runtime closure.

Four focused tests passed on native macOS with the pinned Nix toolchain, including
a Bazel repository query proving both import links are in `@dotnet//:files` and
contain the original bytes. The sixteen existing preparation rejection tests,
Python compilation and whitespace checks also passed. Evidence is retained at
`nix-import-declarations-gzat1xm0` in the native temporary directory.

```sh
python3 -m unittest discover -s tests/graph_execution -p test_nix_imports.py -v
python3 -m unittest discover -s tests/graph_execution -p test_prepare_graph.py -v
```

The Bazel test is explicitly skipped without the pinned Nix SDK/import files and
Bazel override; that skip is not qualification. Integrated exporter-to-preparation
and native Serilog validation remain separate tests. No Linux qualification is
claimed; the user has deferred Linux validation.

## Import text encoding parity

The broader import inventory exposed UTF-8 BOMs and CRLF line endings in SDK
imports. Python's default text reader translated CRLF and retained a UTF-8 BOM,
while .NET File.ReadAllText preserves line endings and consumes encoding BOMs.
Preparation now decodes the hashed import bytes using matching UTF-8/16/32 BOM
selection and preserves newlines. Only hash normalization changes; action restore
staging and runtime policy are unchanged.

The focused preparation regression verifies the hash boundary with CRLF in UTF-8,
UTF-8 BOM, UTF-16 little/big-endian and UTF-32 little/big-endian input, including
workspace path normalization. All seventeen preparation tests pass. The original
integrated package-suite failure involved the SDK WorkloadManifest.targets import;
full native compatibility is rerun separately after this correction.
