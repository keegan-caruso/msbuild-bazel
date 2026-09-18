# Remote action-cache qualification protocol

Use the pinned real bazel-remote 2.6.2 service on loopback and the existing
macOS ARM64/Nix SDK 10.0.400/Bazel 8.4.2 fixtures. This is same-host qualification,
not evidence of independent-machine equivalence or container deployment.

1. Build a producer with no project seeds and action-cache uploads enabled.
   Retain its inner snapshot digest and delete its source/state/output directory.
2. Build one independent seeded primer from that snapshot. Seeds are declared
   inputs and produce a different outer action key. Expect one sandboxed action,
   zero compiles. Delete the primer completely after publication.
3. For three repetitions per fixture, alternate fresh consumers with and without
   the outer action cache. Both reuse the same preparation/project snapshot.
   The outer case must have one remote build hit, no build action and no compiles.
   The inner-only case must have one build action and zero compiles. Actual tests
   remain forced; Serilog must execute its approval test in every successful run.
4. Repeat the same body edit on three fresh read-only consumers. Its action is
   absent from the outer cache and must execute exactly one compile each time.
   Compare unchanged and body outputs with independently warmed raw MSBuild and
   actual app/approval execution. Keep exact DLL/PDB parity.
5. Publish that body-edit action once, then recover it on another fresh consumer.
   Assert an outer hit with no build action and exact edited artifacts.
6. Exercise unique body edits combined with a failing test and a mutation during
   the final lease. Both must stage action-cache writes but publish zero objects,
   publish zero inner-cache objects and leave no committed project cache.
7. Unit controls cover deferred writes, CAS-before-AC ordering, read-only writes,
   discarded staging, invalid paths/digests, read-through and invalid endpoints.
   Existing lease/content/special-file controls remain required.
8. Record complete wall times including preparation, staging, downloads, final
   validation and publication. Report paired outer-hit versus inner-only medians
   separately from raw-MSBuild comparisons. Do not count priming as free startup,
   or claim that arbitrary seed histories share an outer key. Preserve all inputs
   and validation; remote execution remains disabled.
