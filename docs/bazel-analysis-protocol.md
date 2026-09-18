# Bazel analysis and materialization protocol

1. Record runner phase timings alongside existing diagnostics and summarize the
   default Bazel JSON trace. Keep startup, module mapping, SDK package loading,
   the interval before the first build action, sandbox setup, test runfiles,
   MSBuild execution, runtime export and VSTest separate. Nested spans overlap:
   sandbox times are inside action times; the pre-action interval includes more
   than analysis. Do not sum these into a fictitious disjoint breakdown.
2. Measure three repetitions of unchanged/body-edit diamond and Serilog with
   the pinned real cache service, deleted producer, fresh consumer build state,
   shared SHA-keyed Bazel install and verified repository cache. Keep the same
   raw MSBuild comparison, exact DLL/PDB parity, application/approval test
   execution and zero/one compiler work sets as the integrity streaming protocol.
3. Inspect the SDK repository and actual declared action inputs. Reduce repeated
   enumeration only if a measured repeat exists; preserve all declared files.
   Target count alone is not evidence of repeated MSBuild work. Document rejected
   alternatives and retain the current representation if the trade is unfavorable.
4. Optimize redundant runtime export work if profiling supports it. Preserve
   cache bundles, sealed current runtime, the public app tree, independent test
   scratch and full validation. Repeat the same 12 paired comparisons after this
   change. Verify exported payload/metadata parity independently of timings and
   run mutation/corruption/failed-test controls relevant to the touched boundary.
5. Sequential runs on an interactive same-host machine are subject to noise.
   Report phase savings separately from end-to-end changes and keep the
   adapter <= 1.25 * raw + 0.250 s diagnostic target. No independent-worker,
   remote execution, cold-build or cross-platform claim follows from these runs.
