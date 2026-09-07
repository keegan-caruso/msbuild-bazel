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

## Integrated compatibility after import discovery

At frozen production commit `6c6ba18`, the full `tests/graph_packages` suite passed
all seventeen tests on native macOS in 192.284 seconds. This includes the three
pinned package policy checks, ordinary and isolated PrivateAssets behavior across
four modes, and twelve restore-freshness regressions. The prior SDK import hash
failure is resolved. Native PrivateAssets evidence is retained at
`graph-private-adapter-l3_a2x3k`; the full log is
`/private/tmp/r04-final-package-suite-fixed.log`.

Both `tests/configured_execution` tests also passed at that frozen commit in
136.925 seconds, using the explicit Nix Python 3.13.9 interpreter and pinned SDK
and Bazel overrides. The same-path red/blue graph retains separate identities,
converges the changed edge with only Right and App rebuilding, and recovers its
cold bundle bytes from the disk cache after relocation. The selected existing
inner framework also passes cold, unchanged and relocated recovery assertions.
Unsupported outer and default-transitive configurations remain explicit negative
controls. Evidence directories are `configured-execution-kct5tqfa/probe` and
`configured-execution-x_afzaye/probe`; the full log is
`/private/tmp/r04-final-configured-suite.log`.

```sh
python3 -m unittest discover -s tests/graph_packages -v
/nix/store/xcjk9ill54kjk8mzgq6yydnx9015lidg-python3-3.13.9/bin/python3 \
  -m unittest discover -s tests/configured_execution -v
```

These are compatibility checks for the bounded package and configured-node
contracts on macOS, not a performance measurement, remote-cache qualification,
or Linux validation. The Serilog pilot acceptance remains separately reported.
