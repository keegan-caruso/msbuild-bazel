# Stable seed publication and automatic action-cache priming

## Remove history-dependent copied runtime bytes

An API-based project cache hit can contain old copy-local dependency DLL/PDB/XML
bytes even though the current runtime is composed correctly. Those historical
bytes used to reach the next Bazel action as seeds, creating different action
keys for the same sources reached through different build histories.

After a successful graph finishes, the evaluated API/runtime lane now refreshes
only changed copied project runtime files in a new sealed bundle. It uses the
current producer's own artifacts, preserving the SDK-selected file membership,
package assets, reference outputs and replay metadata. Input bundles remain
immutable. Bundles already containing current bytes are not copied. Compilation
reuse still follows the existing API-based identities.

## Producer-side priming

An uploading workflow compares its declared seed content with its accepted output
cache. If they differ, it runs one additional `//:build` using the complete current
seeds in the existing Bazel session. The primer must compile zero projects and
produce exactly the previously accepted app tree and cache content. Tests already
passed against those identical app bytes. Final source/toolchain lease checks
still run after priming, and all outer uploads remain staged until acceptance.

The report separates primary execution counts from `cachePrime` and records the
cost in `phases.primeActionCache`. An unchanged fully seeded producer avoids the
extra action. Read-only consumers never prime. This replaces the separate manual
primer invocation used by the earlier qualification harness.

Priming is an optimization: if it fails, the controller restores the original
accepted bundle/diagnostics, reports the priming error, and discards all staged
outer-cache writes. The already-tested primary build and its independently
validated inner-cache publication can still succeed. A failed test or final lease
continues to reject the whole workflow and publish neither cache.

## Explicit boundaries

Seeds remain real, declared action inputs. Seed-free, partially seeded and fully
seeded actions still have different keys. We do not alias distinct Bazel actions
or hide seed inputs. Producers populate the common fully seeded variant, and
current runtime normalization removes the demonstrated history-dependent byte
variation within that variant. Arbitrary non-deterministic projects, optional
seed subsets, other runtime-selection policies and cross-platform reuse remain
outside the qualification.

## Qualification protocol

`seed_history_probe.py` runs the pinned Serilog graph through two histories:
first build the original source then apply a body edit using project-cache seeds;
separately compile that edited source from scratch. It compares the complete
published per-project key/blob catalog, then requires both snapshots to recover
the exact same outer action key with zero builds/compiles and real approval tests.
It deletes each producer before consuming its snapshot.

A fake Bazel entry point delegates the primary test to the real pinned Bazel but
fails only the optional follow-up build. This checks original-output restoration,
successful primary acceptance, and discarded outer publication after primer failure.
The normal action-cache matrix retains changed builds, raw artifact equality,
forced tests, failed-test and live-lease rejection controls.
