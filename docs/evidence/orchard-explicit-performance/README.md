# Orchard benchmark evidence

See [protocol and interpretation](../../orchard-explicit-performance.md).

- `qualified-results.json`: final graph, retained production changes, two workers.
- `final-results.json`: runtime-qualified 1 GiB retention run and raw MSBuild controls.
- `cache4-results.json`: same retention experiment with a 4 GiB bound.
- `baseline-results.json`, `indexed-results.json`: exploratory pre-qualification runs.
- `worker-phase-totals.json`: cumulative counters across 202 projects, not wall time.
- `resource-edit.json`: setup CSS edit and affected project actions.
- Runtime reports contain HTTP status, content type, size and SHA-256. Setup HTML
  includes dynamic values; compare static asset hashes rather than the page hash.

Individual timings include process startup and are not medians. Compiler warnings
about missing SourceLink information are expected for the disposable checkout.
Large logs, profiles, generated BUILD files, downloaded packages and build outputs
are intentionally excluded from Git.

- `remote-results.json`: loopback seed and relocated recovery, all outputs.
- `recovered-runtime.json`: setup page and static assets from recovered outputs.
