# Native runtime closure: first slice

Run `python3 tools/probe_bazel.py --native-runtime-probe --output artifacts/native-runtime-1`
inside the pinned Nix development shell. This opt-in experiment requires both
Python and .NET under `/nix/store`; preparation must reject non-Nix tool paths.

Before compilation, query the transitive Nix references of the actual Python
executable, standard library, core library and .NET SDK. Enumerate their file
payloads into a manifest and expose those files through a local Bazel repository.
Both project actions receive the closure and manifest. Keep absolute Nix paths,
the host compatibility salt and `no-remote` policy.

Acceptance:

- The existing cold, unchanged, project-edit and local disk-cache matrix passes
  under the native sandbox, with runnable DLL and apphost results.
- Every manifest file appears in both cold execution input logs.
- Removing the closure declaration fails before MSBuild compilation, even when
  the original store files remain on the host.
- An opt-in e2e test checks the matrix and native library inputs.

This is a conservative Nix reference closure, not an observed loader trace or
proof of filesystem hermeticity. macOS dyld/system frameworks and `/usr/bin`
tools remain host dependencies. Dynamically computed paths can escape Nix's
reference graph. No binary package asset, Linux or remote execution claim is
part of this slice. Do not mutate installed store files to test invalidation.
