# Borrowed package validation

A borrowed package file is a private symbolic link to a declared, read-only Bazel
input. The parent validates input bytes before staging and again after MSBuild,
projection and dependency validation. The child now checks that each borrowed
link still points to exactly that declared path and remains read-only instead
of hashing those same package bytes twice more. Namespace checks and all checks
on private copies, source files and restore metadata remain. Restore files that
were replaced with private normalized copies are excluded from the borrowed map.

The contract lasts for one action. This does **not** memoize package digests
across separate project actions or trust modification times instead of content.
Cross-action reuse still needs an immutable worker/input-store contract.

Controls cover retargeted aliases with identical bytes, private replacements,
writable package inputs, package content mutation, and cleanup preserving shared
inputs. Native producer-deleted cache recovery passes with zero compilations;
a dependency body edit executes one compilation and leaves unrelated packages
remote. Invalid action publication and retry controls also pass.

Measurements use six alternating isolated Orchard entry actions, with package
borrowing enabled for both baseline and candidate. Every entry/API/runtime file
must match byte for byte. See the accompanying evidence JSON for measurements.
This is not a full-graph or raw-MSBuild comparison.

Reproduce with `tests/remote_workers/optimization_probe.py`, supplying a request
with `borrowPackageInputs: true`, both runner DLLs, the retained execroot and a
fresh output directory. Do not pass its `--borrow-package-inputs` switch: that
switch measures copying versus borrowing, a different change.

Median action time: **20.065s → 19.709s (1.8% faster)**,
with 6,932 identical files. Child hash checks fall from 2.359s to 0.218s;
the retained parent package revalidation rises from 1.535s to 3.140s,
so the end-to-end win is small. This is not a major cold-build improvement.
