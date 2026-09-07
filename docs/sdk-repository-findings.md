# Optional SDK import repository inputs

The local SDK repository includes `imports/**` only when external imports are
actually declared. `sdk/**` always remains required; `allow_empty=False` keeps an
empty SDK fail-closed rather than hiding missing tool inputs.

On macOS with pinned Bazel 8.4.2, `python3 -m unittest discover -s
tests/sdk_repository -v` passed all three real repository-query controls in
15.358 seconds: no optional imports with a nonempty SDK succeeds, an explicitly
declared Nix import is included, and an empty SDK fails glob evaluation. Queries
do not execute the stub SDK. Log: `/private/tmp/sdk-import-glob-tests.log`.
