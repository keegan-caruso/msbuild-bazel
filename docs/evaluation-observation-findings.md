# MSBuild filesystem observation coverage

SDK 10.0.400 on native macOS ARM64 passes 12 plain-versus-recorded evaluation
cases at `/private/tmp/rul5-observations-1/report.json`. This is coverage evidence,
not preparation reuse authorization.

`tools/EvaluationProbe` injects MSBuildFileSystemBase using ProjectOptions and
ProjectGraph's project-instance factory. It forwards all public filesystem
operations and records their results. Projects are unloaded after creating their
instances; warm rounds retain the shared evaluation context. The probe compares
configured nodes, selected properties/items, references and actual nested imports.

```sh
python3 tools/probe_evaluation_observations.py --output /tmp/evaluation-observations
```

The missing optional-file probe and import/source enumerations are visible.
Adding/removing optional imports and wildcard matches changes those observations.
Global-property changes preserve ordinary/recorded parity. Actual SDK evaluation
includes generated NuGet import wrappers in ImportPaths.

However, this pinned implementation bypasses the custom read methods when loading
project/import XML. Warm shared evaluation caches suppress most enumeration calls.
A System.IO.File.ReadAllText property function reads a file without any corresponding
hook observation: changing that file changes evaluated properties with an equal
hook trace. Item ModifiedTime metadata also bypasses GetLastWriteTimeUtc.

Therefore the trace alone is not eligible discovery identity. ImportPaths supplies
a content cross-check, but hashing imports after mutable evaluation does not prove
which bytes the XML loader used. Capturing an immutable input view and controlling
fresh evaluation/cache state remain necessary. The next implementation must cover
unobserved reads using a sealed declared-tree fallback and a restricted evaluation
boundary, or reject eligibility. It must not treat the observed subset as complete.

The forwarding recorder is an experiment; it executes no targets or tasks. It
records raw observation paths and preserves enumeration order. It does not claim
GraphExport's target-time input discovery is covered, solve publication, or establish
performance improvements. RUL-6 and RUL-7 retain those separate gates.
