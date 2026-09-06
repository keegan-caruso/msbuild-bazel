# Remove Python from Bazel project actions

Replace tools/bazel_action.py with a framework-dependent net10.0 console app
built during preparation. Bazel launches the declared SDK dotnet executable with
the runner DLL. Declare its DLL, deps.json and runtimeconfig.json as inputs.
Retain Python probes, package preparation and unittest harnesses outside actions.

Preserve request JSON, bundle metadata, package validation, replay isolation,
compiler path mapping, normalized permissions/timestamps and diagnostics. Find
the actual SDK host through Environment.ProcessPath so restored SDK tokens and
MSBuild use the same SDK under symlinked sandbox paths.

Remove local_python_runtime and Python-only rule attributes. The action host salt
must no longer contain Python version/runtime paths. Keep fixed action env and
no-remote policy. Native runtime inventory starts at the SDK only.

Acceptance: full local suite and both Linux workflows; retained native probe;
no Python executable or standard library in any cold action input/command;
runner runtime files declared; unchanged scheduling and local disk-cache reuse;
fresh staging equality; package/native/undeclared-input rejection before compile.
