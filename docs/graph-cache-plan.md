# Next graph work

The graph workflow is now the sole backend. The runtime qualification milestone
closed compilation, source-host execution, eight-suite outcomes, body/API/native
controls, independent HTTP recovery, cache faults and matched timing. See
[current support](implementation-plan.md) and [performance](performance.md).

## Order

1. Requalify source-built SDK and NativeAOT consumers after the interface cutover.
   Keep bootstrap SDK/native tools separate from the SDK they produce.
2. Audit graph publication: the earlier 263-compilation artifact contained
   428.5 MB declared products, 358.2 MB package archives, 67.3 MB source and
   22.5 MB other artifacts. Review those other artifacts before reducing publication.
   Preserve Restore, target results, layouts, app/tests and independent replay.
3. Investigate private Restore invalidation and body/API staging with the current
   large runtime graph. Retain only changes with correctness controls and matched
   profile-off wall measurements.
4. Expand reviewed runtime slices and generic sync contracts gradually; qualify
   platforms and remote execution independently.

## Measurement contract

Prioritize incremental body and API edits. Match raw graph configurations, dependency
roles, Restore state, native products and resources. Record complete Bazel/raw wall
cost, actual Csc calls, project hits/misses and separate diagnostics. Recovery needs
fresh paths and stopped producers. Never count a local warm build as independent
remote-cache qualification. Keep raw reports outside the repository and summarize
results and limits in the scorecard.
