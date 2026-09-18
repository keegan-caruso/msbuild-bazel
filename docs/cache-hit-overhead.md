# Cache-hit overhead follow-up

## Outcome

Two isolated changes improve fresh remote recovery while preserving exact DLL/PDB
parity, application execution and approval-test acceptance. Profiling identifies
repeated Bazel registry work as the next opportunity. The raw-MSBuild target is
still missed.

Three-repetition medians, seconds:

| Unchanged workload | Previous baseline | Shared final scans | Shared scans + installed Bazel | Overall reduction |
|---|---:|---:|---:|---:|
| Four-project diamond | 8.460 | 7.538 | 7.029 | 16.9% |
| Serilog approval graph | 12.861 | 11.724 | 11.199 | 12.9% |

Raw MSBuild medians in the final run were 0.585 s and 1.059 s respectively.
Body-edit medians with both changes were 7.531 s (diamond) and 11.434 s
(Serilog), with exactly one compilation each. Unchanged consumers compiled zero
projects. All 18 new comparisons passed exact managed DLL/PDB equality against
raw MSBuild and actual application/test execution.

These are sequential same-host measurements on the same pinned macOS ARM64
setup as the [baseline](dotnet-worker-performance.md). They are not randomized
causal estimates or independent-worker acceptance. Phase traces corroborate the
specific savings, but full wall-time differences include run-to-run variation.
Cold/API cases were not repeated in this focused follow-up.

## 1. Share reads inside one final validation pass

Commit `45ea5b0` introduces a pass-local verification object keyed by exact root
and symlink-following policy. Discovery and the outer workflow share snapshots
for overlapping roots. Each expectation is still independently compared, so a
conflicting baseline cannot be hidden by a previous successful check. No
validation result persists into the next invocation/pass. Unshared callers still
get a fresh verifier.

The measured pass has 51 requests but only 31 scans. Final validation drops from
2.316 to 1.228 s on diamond and 2.627 to 1.463 s on Serilog. Initial toolchain
hashing remains; this does not trust timestamps or skip SDK checks.

Tests reject changed content, including same-length edits with restored mtime,
conflicting expectations, and mutation between validation passes. Different
symlink policies do not share reads. Verification retains the preexisting
before/after validation model; it is not an atomic filesystem snapshot.

## 2. Reuse the installed tool separately from build state

Commit `3a65db8` adds optional `--bazel-install-cache`. The workflow derives an
installation directory from the exact already-verified Bazel executable digest.
Only that extracted distribution is shared. Each consumer retains a new output
base, user root, server, action cache, source tree and preparation state. The
option stays explicit because worker tool provisioning determines its lifetime.
See [usage](native-workflow.md#optional-bazel-installation-reuse).

The producer provisions the installation, then its source/state/server are
removed before consumers run. Each consumer asserts no state directory existed
before invocation and no installation-extraction message appeared. Shutdown
uses the same installation startup option to avoid restarting a server with
mismatched startup settings. Exact output parity and compile counts guard the
fresh-worker comparison.

Bazel launch medians drop from 0.768 to 0.494 s for diamond and 0.781 to 0.475 s
for Serilog. Extraction itself previously took 0.259/0.254 s and is absent in all
shared-install consumers. Full workflow medians improve a further 0.509/0.525 s;
only roughly a quarter-second is directly attributable to extraction from the
trace. A worker without a provisioned installation still pays the first-use cost.

## 3. Profile the remaining Bazel phase

The checked-in parser reads Bazel's existing compressed JSON traces; no extra
profiling instrumentation was added to the measured commands. It records
main-thread phase boundaries, launch/extraction, module mapping, download spans,
sandbox creation and action critical-path components. Download intervals are
unioned to avoid double counting concurrent spans. Nested fields overlap and
must not be summed as independent portions of wall time.

Final unchanged profile medians:

| Trace measurement | Diamond | Serilog |
|---|---:|---:|
| Bazel phase (controller wall clock) | 3.989 s | 6.019 s |
| Launch | 0.494 s | 0.475 s |
| Module mapping | 1.627 s | 1.666 s |
| Registry download spans (count) | 155 | 155 |
| Union of download spans | 1.545 s | 1.576 s |
| Action critical path | 0.565 s | 2.176 s |
| Sandbox filesystem creation, summed | 0.196 s | 0.459 s |

The registry spans include BCR module files for platforms, rules_java,
rules_license, protobuf and their dependency resolution. A fresh generated
workspace/user root repeats this work. The earlier 36–61 ms HTTP figures measured
our native artifact CAS only; they omitted Bazel's separate registry traffic.
The 155 trace spans are not a server-side network-request counter, and registry
payload bytes were not collected.

**Next implementation target:** provision a pinned module lockfile and a reusable,
verified Bazel repository-download cache outside ephemeral build state, then
measure them independently. Preserve empty project/action caches and deleted
producers in that experiment. After that, separate remaining analysis cost from
native output materialization and test sandbox setup. Sharing an installation
alone does not eliminate server startup, module resolution or analysis.

## Reproduce

Use the same SDK, upstream checkout, packages and pinned bazel-remote binary as
the baseline protocol. Initial restore and tool acquisition remain outside the
clock for both raw and adapter builds; each measured adapter invocation is fresh.
No build/test work occurs concurrently with timing samples.

```sh
# At 45ea5b0: shared scans, isolated Bazel installation.
python3 tests/remote_workers/measure.py --cache-binary "$CACHE_BINARY" \
  --packages "$PACKAGES" --checkout "$SERILOG_CHECKOUT" \
  --output "$SCAN_RESULTS" --repetitions 3 --cases unchanged

# At 3a65db8: same validation, separately provisioned Bazel installation.
python3 tests/remote_workers/measure.py --cache-binary "$CACHE_BINARY" \
  --packages "$PACKAGES" --checkout "$SERILOG_CHECKOUT" \
  --output "$INSTALL_RESULTS" --repetitions 3 --cases unchanged body \
  --bazel-install-cache "$INSTALL_CACHE"

python3 tests/remote_workers/overhead_summary.py \
  "$SCAN_RESULTS/report.json" "$INSTALL_RESULTS/report.json" --output "$SUMMARY"
python3 tests/remote_workers/profile.py \
  "$SCAN_RESULTS/report.json" "$INSTALL_RESULTS/report.json" --output "$PROFILES"
```

[Timing evidence](cache-hit-overhead-evidence.json) retains all new samples,
compiler counts, validation-scan counts, phase/transport measurements, revisions,
harness hashes and source-report hashes. [Profile evidence](cache-hit-profiles.json)
also covers retained baseline traces. The baseline `wm1` report includes only
completed passing diamond samples; its overall failure from the corrected
Serilog comparator remains labeled. See the baseline protocol for that history.

Bazel's [output layout](https://bazel.build/remote/output-directories) and
[JSON trace documentation](https://bazel.build/advanced/performance/json-trace-profile)
describe the installation/output separation and profile field units used here.

## Validation

Both measured changes passed exact output/execution acceptance. Final
`scripts/check-dotnet.sh` passed owned .NET build, warnings and formatting checks,
5 style-policy tests, 32 preparation tests and 21 workflow tests. The strengthened
same-length/restored-mtime rejection control passed. `scripts/check.sh`, harness
Python compilation and `git diff --check` also passed. No GitHub CI was run.
