# Two-target Bazel experiment contract

`python3 tools/probe_bazel.py --output ABSENT_DIRECTORY` prepares a copied fixture,
restores NuGet metadata, and builds the replay plugin outside Bazel compilation
actions. It then runs two explicit `msbuild_project` actions, Shared followed by
App. This is a fixture adapter, not a general graph exporter.

Shared receives only its own sources, project and normalized restore metadata,
common imports/configuration, the runner, replay plugin and SDK file inputs.
It captures the explicit six-target dependency contract in a Shared-only graph
build. App receives its sources, both project files for graph evaluation, common
imports, both normalized restore states and Shared's bundle. Shared source files
are deliberately absent from App's declared inputs and scratch workspace.

Each action copies declared inputs into its own fresh scratch workspace. Restore
metadata is expanded from explicit workspace/SDK tokens; compilation does not
restore or download tools. App stages and validates Shared's dependency bundle,
then uses public-API replay with `-graphBuild -isolateProjects`. Shared and App
outputs are separate Bazel tree artifacts with retained action reports and logs.
The SDK tree participates in the action digest. The host Python interpreter,
shell, native libraries and Nix runtime closure are not yet hermetic toolchains;
reports and rule configuration record the chosen host runtime. No remote-cache
or remote-execution correctness is claimed.

The harness requires sandbox execution (no automatic local fallback) and writes
Bazel JSON execution logs. Acceptance cases are cold (Shared and App execute),
unchanged (neither), App edit (App only), Shared edit (both), cleared outputs with
the disk cache retained (both restored), and a fresh Bazel output base using the
same disk cache. It asserts execution records, compilation markers, distinct
action workspaces, absence of Shared sources in the App action, and runnable App
output through both the DLL and native app host, preserving executable modes.
A negative undeclared-input probe must fail inside the action sandbox.
Sandbox platform limitations must be reported explicitly, never hidden by a
fallback to local execution.
