# RUL-6: leased export and preparation reuse

The opt-in `tools/preparation_reuse.py` path reuses the RUL-5 qualified
Release/net10.0 GraphExport slice on native macOS ARM64 with the pinned Nix
SDK 10.0.400. It requires prebuilt GraphExport, EvaluationProbe, ReplayPlugin
and ActionRunner tools. Existing `prepare_graph.prepare` callers retain fresh
preparation; consumers opt in with the new context manager or command below.

## Usage and lifetime

From the Nix development shell, build the four tools with
`bash scripts/dotnet.sh build tools/<name> -c Release --nologo`, then supply a
restored source directory and the entries JSON described in
[the discovery contract](discovery-contract.md):

```sh
python3 tools/preparation_reuse.py --workspace /path/to/restored-source \
  --state /path/to/owned-cache --output /path/to/new-consumer \
  --entries /path/to/entries.json -- /path/to/bazel build //:all
```

The output directory must be new and disjoint from source/cache. The command
runs in that consumer workspace while both the cache and discovery-view exclusive
leases are retained. Python callers use `with prepared_view(...) as result:` and
finish consumption inside that block. The result reports `reused`,
`discoveryExecuted`, `materializationExecuted` and `toolBuildsExecuted`.
Without a command, the lease covers verification and materializing the standalone
consumer copy. A saved report does not grant subsequent access to the mutable
discovery view.

Unchanged runs still seal and hash the complete input view, verify the prepared
payload and copy it to the consumer. They skip the evaluation recorder, full
GraphExport, materializer, package staging and tool builds. This is a correctness
boundary; the cost of the conservative full-tree checks is RUL-7's measurement.

## Opt-in incremental preparation experiments

See [the sequential experiment](incremental-preparation-findings.md) for measured
results and limits. The default keeps full content verification. Two independent
options are available:

- `--trust-system-nix-store` keeps a process-local verification cache for protected,
  root-owned Nix store generations on macOS. It explicitly trusts privileged Nix
  administration and storage integrity for the session. Restart after store repair
  or administrative changes. No persisted receipt grants trust. User-owned trees,
  writable entries and entries with ACLs retain full hashing. A persistent Python
  caller can pass the same `ProtectedStore()` object to successive `prepared_view`
  calls; a CLI process starts with an empty store.
- `--incremental-sources` allows existing C# source contents to change without
  rerunning evaluation or GraphExport when every other qualified input, namespace,
  mode and request field is unchanged. It publishes a new materialized generation
  with updated content hashes and a certificate recording its parent and changed
  files. Resources other than explicitly named unchanged XML, and additional-input
  graphs, keep full discovery, as do
  membership, import, restore, toolchain and request changes. Input validation and
  normal compilation still run.

These flags bind separate preparation request policies. Enabling or disabling one
invalidates the previous request. The original observation digest in a derived
certificate identifies the recorded evaluation whose structure is reused; it is
not evidence of a new evaluation. Full mutable-checkout content validation remains
required: absent file events and stable timestamps do not prove unchanged bytes.

## Identity and publication

The request binds entries, explicit environment/test choices, materialization
operation, Python controller/policy files, Bazel rule files, SDK location and the
complete four prebuilt tool trees. The RUL-5 certificate separately binds the
staged paths, normalized timestamps, controlled discovery environment, runtime
closure, host/boot identity, graph digest and external negative observations.

Only the qualified default environment and build-only request can reuse.
Explicit tests, custom environments and unsupported discovery behavior use the
existing fresh exporter/materializer path. Failed fresh preparation is still an
error; unsupported inputs are not silently granted a certificate. Consumer
failures propagate without retrying their command.

Each generation includes the graph, source/restore/package payloads, runner,
plugin, rule files and all generated declarations. An integrity manifest binds
all payload bytes, file modes and directory membership. The commit pointer binds
the manifest digest; the graph must also match the discovery certificate. Missing
or corrupt state rejects reuse and creates a freshly qualified generation.

Publication writes into an unselected pending directory, flushes its files and
directories, renames the complete generation, then atomically replaces and flushes
the commit pointer. Interrupted pending directories are discarded on the next
locked invocation. Complete unreferenced generations are safe to ignore. Old
committed generations remain retained; automatic garbage collection is outside
this slice. Builds operate on separate consumer copies, so Bazel output symlinks,
module lockfiles and compilation outputs cannot mutate the cached payload.

The locks serialize cooperating consumers and publishers through the entire
context. This is an owned local cache, not protection against a malicious process
with permission to rewrite it. Digests detect corruption, not forgery. The atomic
rename/fsync protocol targets local filesystem semantics, not network filesystems
or a remote artifact store.

## Relocation and scope

Restored source can be copied to a different location and its generated restore
paths relocated before deleting the producer. RUL-5 seals it back at the same
owned discovery path. Identical supplied bytes can then recover the prepared
payload into a new consumer workspace. Moving the cache/discovery root, changing
the host or boot session invalidates the path-bound certificate and requires
fresh qualification. Cross-host preparation reuse is not claimed.

This does not extend discovery eligibility to arbitrary SDKs, custom MSBuild
targets, tests, other frameworks or packages. The existing RUL-5 SDK/Serilog
allowlist remains the boundary. Broader invalidation qualification belongs to
RUL-8; useful performance and validation cost belong to RUL-7.

## Validation

```sh
python3 -m unittest discover -s tests/preparation_reuse -v
python3 tools/probe_preparation_reuse.py --output /tmp/rul6-native
```

The native probe retains reports and logs for cold/unchanged preparation,
timestamp-only changes, source invalidation, missing/corrupt payloads and
metadata, interrupted publication, producer-free relocation and actual native
sandbox execution from recovered prepared files with an empty Bazel disk cache.
The unit suite covers path ownership, complete payload integrity, request
fallbacks, atomic switch failure and consumer exception propagation.

Final small-graph qualification (2026-09-09, native macOS ARM64, Nix SDK
10.0.400): all 17 cases pass at `/private/tmp/rul6-native-final/report.json`.
This includes two concurrent processes, a real runner-input change, interruption
at the commit-pointer switch and two fresh `darwin-sandbox` actions with an empty
Bazel disk cache after deleting the source and earlier consumer workspaces. The
recovered application prints `recovered-rul6`. The 40 identity/contract/reuse unit
tests, 18 existing materializer rejection tests, six framework-selection tests
and seven dependency-closure tests pass. `bash scripts/check.sh` and
`bash scripts/check-dotnet.sh` pass, including the five style-enforcement controls.
No CI workflow was dispatched.

Supplemental pinned Serilog and fresh-fallback probes:

```sh
python3 tests/preparation_reuse/probe_serilog_reuse.py \
  --source /path/to/serilog-git-acquisition --packages /path/to/package-cache \
  --output /tmp/rul6-serilog
python3 tests/preparation_reuse/probe_fresh_fallback.py \
  --workspace /tmp/rul6-native/cache/discovery/workspace \
  --output /tmp/rul6-fallback
```

The pinned Serilog probe passes both cases at
`/private/tmp/rul6-serilog-final-2/report.json`: cold materialization followed by
unchanged reuse after source relocation and producer deletion. The recovered
workspace performs one fresh native sandbox action with an empty Bazel disk
cache. A separately compiled executable references the resulting Serilog DLL,
constructs a logger and prints `Serilog`. This checks actual recovered package,
generator, signing and library consumption, not just manifest equality.


Both actual fresh-fallback cases pass at `/private/tmp/rul6-fallback-final/report.json`.
Unsupported authored XML and an explicit empty test request execute fresh export,
tool builds and materialization, and neither publishes a cache commit pointer.

## External-absence miss correction (2026-09-14)

The readiness review found that a previously absent external file appearing before
candidate validation correctly set `unchanged=false`, but context teardown then
raised the accepted-lease mutation error. That prevented the caller from trying
fresh capture/preparation. The post-consumption external-absence guard now applies
only to candidates accepted as unchanged. A new external file appearing during an
accepted lease still rejects consumption.

`python3 -m unittest discover -s tests/preparation_reuse -q` passes all 43 tests.
The three new candidate-lease regressions cover an external file present before
validation, a file appearing during accepted consumption, and the reuse caller
reaching fresh preparation when the new input is outside discovery eligibility.
The first and third tests failed with the original implementation and pass with
the fix. Host acquisition and staging are mocked in these focused tests; the
candidate decision, context teardown and reuse caller control flow are real.

The temporary worktree had lost tracked and untracked files between sessions.
Missing tracked files were restored from its unchanged base commit, and missing
RUL-6 additions were reconstructed from this task's recorded edits. Surviving
modified files were preserved. Main was not changed.

Native validation also passes all 27 cases with the pinned Nix SDK:
`python3 tools/probe_discovery_contract.py --output /private/tmp/rul6-external-miss-fix`.
The report is `/private/tmp/rul6-external-miss-fix/report.json`, including
`external-absence-invalidated` and `masked-external-input`. Both discovery tools
rebuilt with zero warnings/errors. `git diff --check` passes. No CI was dispatched.

## Local merge qualification (2026-09-14)

GitHub full Linux run `34863017842` was rejected before the job started because
of account billing/spending limits. The user explicitly authorized local validation
and merge without waiting for GitHub CI; the CI-waiting follow-up was paused.

Fresh validation on native macOS ARM64 with the pinned Nix environment passes:

- `bash scripts/check.sh`: toolchain and Starlark formatting/lint checks.
- `bash scripts/ci-linux.sh quick`: all local quick checks, including 43
  preparation tests, 21 graph tests, owned .NET style/warnings and all 20 Starlark
  tests. Log: `/private/tmp/rul6-local-quick.log`.
- The 31 focused tests in `test_prepare_graph.py`, `test_framework_selection.py`
  and `test_dependency_closures.py`.
- `python3 tools/probe_preparation_reuse.py --output /private/tmp/rul6-local-merge`:
  all 17 cases, including missing/corrupt state, interrupted publication,
  two-process serialization, runner-input invalidation and producer-free execution
  of two fresh native sandbox actions. Report: `/private/tmp/rul6-local-merge/report.json`.

These are local macOS results. The billing-blocked GitHub run supplied no Linux
validation evidence, and full Linux acceptance was not run locally.
