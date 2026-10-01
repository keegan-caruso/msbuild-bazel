# Graph output publication audit

The source-runtime application graph publishes its whole staged workspace.
This read-only audit classified files against its explicit output directories
and output files. It did not remove files or change publication behavior.

## Observed size

Linux ARM64, pinned runtime v10.0.0, SDK 10.0.400, Bazel 9.2.0;
130 physical projects, 298 configured nodes and 263 compilations.
The artifact is the producer from the
[independent application recovery](runtime-graph-application.md).

| Category | Files | Bytes |
| --- | ---: | ---: |
| Declared output directories/files | 6,463 | 428,522,873 |
| Package archives | 164 | 358,203,852 |
| Source tree | 6,323 | 67,325,658 |
| Other artifacts outside declared outputs | 650 | 22,548,696 |
| Imports, configuration and notices | 38 | 445,012 |
| Total | 13,638 | 877,046,091 |

No declared source input in this artifact overlaps a declared output path.
The other-artifacts category is not yet reviewed for ownership or consumers.
These sizes describe uncompressed files, not wire traffic or cache size.

## Proposed change and gates

Publish only declared products after successful input verification. Retain the
full execution workspace until MSBuild and verification finish. Output ownership
must include generated files, resources, shared BinPlace products and any assets
that downstream tools or runtime consumers need.

Before implementation:

1. Audit graph layouts, tool bindings, executable/test data and working directories.
2. Prove generation, resources and source-adjacent output paths in small fixtures.
3. Reject missing or overlapping ownership instead of silently discarding assets.
4. Compare complete declared products and run the app/test controls.
5. Repeat body/API edits and independent recovery; measure materialization,
   publication bytes and complete Bazel wall time.

The audit suggests that staged inputs explain much of the publication volume.
It does not establish that deleting those files is safe or faster. SDK validation,
project evaluation and SDK execution are separate costs.
