# One-pass dependency replay placement

Resolve the final producer for every selected runtime path before materializing a
dependency. Restore each artifact from that producer once, keeping every path,
normalization rule, package selection and producer-ownership check. This removes
10,041 overwritten placements from Orchard's entry dependency restoration while
preserving the complete 11,799-artifact filesystem contract.

Runtime selection and bundle refresh now index artifacts by path. Framework
metadata is read once per producer, outside artifact-search predicates. In the
previous refresh loop it was parsed again for each candidate artifact.

Three alternating same-path Orchard pairs after validation reuse:

- Baseline median: 24.789 s.
- Candidate median: 22.879 s.
- Saving: 1.911 s (7.7%).

All six runs produce identical 3,463-file entry bundles. Dependency selection plus
composition drops from about 1.9 seconds to 0.12 seconds; final bundle refresh
falls from 1.15 seconds to about 0.006 seconds. Input staging varies between runs,
so the complete measured action time remains the performance criterion.

Owned builds with warnings as errors and ActionRunner.Tests pass. Tests cover
selected producer ownership, package membership, corrupt producers, rejection
before writing output, and unchanged sealed inputs. Native sandbox acceptance passes producer parity, producer-deleted remote
recovery (zero compiles), one-project body edits, and invalid publication/retry
controls. Raw acceptance evidence: `/private/tmp/replay-placement-native`. Measurements exclude remote transfer and
Bazel scheduling. Raw evidence: `/private/tmp/replay-placement-measure`.
