# Python reference implementations

The Python modules in this directory are retained for test oracles, experiment
harnesses, and reproduction of historical measurements. They are not production
entry points. In particular, `native_workflow.py`, `prepare_graph.py`,
`preparation_reuse.py`, their cache/discovery helpers, and the milestone-one
`adapter.py` are reference implementations.

Production entry points:

- `bash scripts/build.sh`: .NET native Build/Test, preparation reuse and HTTP cache.
- `bash scripts/prepare.sh`: .NET fresh graph preparation.
- `bash scripts/setup.sh`: shell SDK/Bazel bootstrap followed by .NET tooling.
- `bash scripts/tooling.sh setup-starlark` and `bash scripts/check.sh`: .NET tool checks.

Bazel actions execute the existing .NET runners. The production controller uses
only the .NET standard library, with no Python child process or embedded runtime.
See `docs/python-removal.md` for boundary tests and acceptance evidence.
