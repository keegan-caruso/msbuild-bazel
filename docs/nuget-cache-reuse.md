# Reusing the NuGet global packages cache

The production entry point is now .NET. See [the current workflow](native-workflow.md)
and [migration validation](python-removal.md#steps-3-and-4-production-workflow-and-bootstrap).
The measurements below describe the earlier Python controller and cache format;
new .NET snapshots use a separate versioned format.

[Preparation components v3](preparation-components.md) extend the package split
below to sources, metadata, and SDK evidence. These measurements describe v2.

The native workflow now accepts normal restored projects whose packages live in
NuGet's global packages cache. It selects `--nuget-packages`, then
`NUGET_PACKAGES`, then `~/.nuget/packages`. Restore must already be complete;
NuGet remains responsible for acquiring and repairing packages.

```sh
# Restore with the same package-cache selection used by the workflow.
export NUGET_PACKAGES=/absolute/global-packages
dotnet restore path/App.csproj -p:Configuration=Release -p:TargetFramework=net10.0
bash scripts/build.sh \
  --workspace /absolute/source --state /absolute/owned/state \
  --entry path/App.csproj --output /absolute/new/report \
  --trust-system-nix-store \
  --remote-endpoint https://trusted-cache.example/native \
  --remote-snapshot SHA256
```

A different cache selected by NuGet.Config can be supplied explicitly with
`--nuget-packages`. The restored assets must agree with that selection. Multiple
fallback package folders are outside this slice. Existing workspace-local
`.nuget/packages` inputs remain supported.

## Isolated package inputs

`nuget_cache.stage` reads the package closure recorded in restored assets and
copies only those package directories into an owned workspace. Unrelated global
packages are not scanned or copied. Source and package copies are checked against
content snapshots; links and changes during copying reject the staging operation.
Only known restore metadata paths are relocated, using a single substitution pass
so a source path prefix cannot corrupt an inserted destination path.

The staged workspace then goes through the normal discovery/preparation contract:
archive and restore pins, extracted-file contents, namespace, toolchain and lease
checks still apply. Sandbox actions receive declared private files, never access
to the live global cache. Changes to global files after copying cannot change the
private build inputs. Missing packages report that NuGet restore is required;
modified package imports or payloads cannot silently authorize stale reuse.

## Remote preparation v2

Preparation metadata and source files use the existing preparation CAS object.
Each package payload is a separate deterministic ZIP addressed by its SHA-256.
The metadata binds package paths, archive digests, file sizes, modes and digests;
full reconstructed preparation identity is checked before consumption.

A consumer first reconstructs package files from its configured global cache or
its restored workspace-local cache. Every file must match the snapshot's expected
bytes. NuGet-omitted archive bookkeeping is recovered from the pinned `.nupkg`;
the preparation SHA-512 marker is derived from that same verified archive. Missing
or mismatched local candidates can use the verified remote package object. This
transport fallback never edits or repairs the global NuGet cache, and cannot
bypass the independent current-input validation for a build.

Package publication checks CAS existence with HTTP HEAD. Existing objects with
the expected size are not uploaded again; missing objects are uploaded. Services
that return 405/501 for HEAD retain GET/PUT compatibility, with redundant uploads.
Downloads always verify content hashes; HEAD is a transfer optimization, not an
integrity proof for consuming server bytes. Metadata publication remains after
successful build/test and final input checks. Prior v1 preparation snapshots miss
conservatively; the native tool identity also changes with controller code.

Reports include `nuget` staging counts, `phases.nuget`, and
`preparation.remotePackages` with local/remote package counts and reused bytes.
The normal workflow's fresh fallback now keeps its bound prebuilt tools through
both export and preparation revalidation; it does not rebuild them mid-invocation.

## Validation protocol

```sh
python3 -m unittest discover -s tests/preparation_reuse -v
python3 -m unittest discover -s tests/native_cache -v
python3 tests/preparation_reuse/probe_nuget_cache.py \
  --checkout /path/to/pinned/serilog --packages /path/to/seed-global-packages \
  --output /absolute/new/probe --repetitions 3
```

The Serilog probe restores each worker against an independent global cache and
deletes the producer's source, global cache and build state before consumers run.
It measures three unchanged and three body-edit consumers, then checks API/package
changes, missing and modified global packages, corrupt remote package objects,
failed tests and mutation during an accepted input lease. Successful tests consume
runtime bytes matching the current build outputs. It also reconstructs a full
preparation with no local package cache to exercise remote package fallback.

Transfer measurements use loopback HTTP with 10 ms per request. Restore and
initial population of the global cache are excluded, matching the workflow's
restored-input contract. They are not a WAN benchmark. Cold build speed remains
secondary to remote reuse, per the accepted project direction.

## Accepted results

September 17, 2026; pinned Serilog revision
`49b5339ce85385dc52d4d8e8f2b8308becf23506`; SDK 10.0.400, native macOS ARM64.
Three fresh consumers per unchanged/body case; 10 ms loopback HTTP latency.

| Case | Prior download / upload | New download / upload | New workflow median |
|---|---:|---:|---:|
| Unchanged | 49.57 / 46.18 MB | 4.26 / 0.87 MB | 11.82 s |
| Body | 49.41 / 46.34 MB | 4.10 / 1.03 MB | 13.06 s |

Unchanged traffic falls by 91.4% down and 98.1% up; body-edit traffic falls by
91.7% down and 97.8% up. Both reconstruct all 22 package payloads locally, verifying
84,452,504 bytes, without remote package GETs or package PUTs. Unchanged builds
compile zero projects; body edits compile one. There are 28 HTTP requests per
case, including 22 small HEAD requests. This optimizes bytes; higher-latency
services may benefit from a future batch missing-object query.

Prior traffic comes from the original full-payload Serilog control. Its HTTP
latency and workspace-package setup differ, so the timing column describes the
new workflow only and is not a claimed speedup over that old run.

All 13 real-project controls pass. API and package changes compile two projects.
Missing or modified global packages stop without publishing. Corrupt remote
package objects are unnecessary when local reconstruction succeeds, and their
wrong-size objects are repaired at publication. Failed tests and lease mutation
produce no PUTs or build-cache pointer. A separate no-local-cache reconstruction
fetches and verifies all 22 package objects (45.27 MB), proving remote fallback.
Unchanged runtime hashes match the producer; body edits change the runtime, and
tests consume the current exported runtime bytes.

Validation: 111 preparation tests and 33 related cache/tool/package tests pass.
The four package-free fresh-consumer regression cases also pass exact raw-runtime,
reference-assembly and executable-output comparisons. No C# code changed and no
GitHub CI was run. Evidence: `/private/tmp/mng-final/report.json` and
`/private/tmp/mng-scale/report.json`.
