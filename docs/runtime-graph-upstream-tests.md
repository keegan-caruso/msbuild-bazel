# Runtime graph test-host qualification

The graph path now declares the library and shim inputs needed to extend the
source-built app host toward runtime's actual VSTest harness. Test execution is
still being qualified; this is not an eight-suite passing result.

## Verified checkpoint

Runtime v10.0.0 (`60629d14374c56f1cb51819049ad1fa529307f8d`), SDK 10.0.400,
Linux ARM64 and Bazel 9.2.0. The VM has four CPUs and 8 GiB; graph workers use
four MSBuild nodes. These are unscored correctness checks.

| Check | Observed result |
| --- | --- |
| App/platform/Pipelines graph | 133 projects, 303 configurations, 267 compilations; managed Build passes |
| VSTest on the original 58-library source host | Fails because source-built `System.Diagnostics.TraceSource` is absent |
| Expanded library/shim/Pipelines sync | 253 projects, 536 configurations, 474 compilations; offline sync passes |
| Expanded host declaration | 123 managed assemblies and eight native binaries; includes TraceSource, XML and 17 authored Linux shims |
| Small metadata generator | Generated source/assembly changes on a declared metadata-file edit; restoration replays one project with identical bytes |
| Document guard | A changed generation-target hash is rejected |

The smaller test attempt also exposed a fixture mistake: composing a layout at
its root requires `"."`, not an empty destination. No production rule changed.

## Declared inputs

The reviewed shim stub target generates C# from `ForwardedType` metadata before
`CoreCompile`. Its document hash and target name are pinned, and each of the 19
stub projects declares that item as metadata. Generated files remain in the
SDK intermediate output directory.

The pinned JavaScript import generator declares an empty IDE `Folder` item.
Its project hash and scoped metadata declaration preserve that fact without
inventing recursive file inputs. The reviewed source contains no translations
in that empty folder.

The larger graph adds the authored API compatibility baseline
`Microsoft.Bcl.Memory/9.0.0`, SHA-256
`102832679dd7a89a117197b142972d12ad671c55ee5b862a152c7b125b1a7bb5`.
API validation remains enabled. All declarations are qualification mappings;
production rules contain no runtime-specific special case.

Reproduce preparation with an explicit feed containing the pinned archives:

```sh
python3 tests/graph_build/upstream/runtime_prepare.py \
  SOURCE_ARCHIVE PACKAGE_FEED NEW_DIRECTORY \
  --slice loaded-common --also-slice loaded-platform \
  --also-slice loaded-libraries --also-slice loaded-shims \
  --also-slice pipelines --prepared-restore
```

Run the independently reproducible small fixture after building ProjectSync,
with the pinned SDK and Bazelisk overrides set:

```sh
python3 tests/graph_build/forwarded_types.py NEW_LINUX_ARM64_DIRECTORY
```

It runs public sandboxed graph workers with remote caches disabled. Project-file
edits require resync; the replay control instead edits an explicitly declared
metadata file. Large logs and report JSON remain outside Git.

## Remaining gates

Complete expanded Build/replay and shared BinPlace ownership, then execute
Pipelines with the source host. Compare complete raw compiled products and exact
VSTest case names/outcomes. Check observed source-producer hashes, deliberate
failure, SDK-absent execution and dependency edits before expanding the suites.
Repeat the relevant controls on Bazel 8.8.0. Build and test timings must be separate.

A disk-full interruption made the qualification filesystem read-only. That trial
is excluded. After preserving diagnostics, restarting only the owned build VM
and removing obsolete staging, host free space reached 62 GiB before the retry.
No passing test or performance claim is derived from the interrupted run.

The separate [publication audit](runtime-graph-publication.md) identifies staged
input bytes that may be removable after consumer and ownership review.
