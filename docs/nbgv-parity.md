# NBGV parity fixture and late adapters

`adapter_imports` on explicit assembly rules imports declared `.targets` files
immediately after SDK targets (including restored package targets). They remain
ordinary read-only action inputs. Worker path mapping applies to these imports.
Shared restore is rejected when adapters are present. No package-specific logic
was added to the runner.

`tests/explicit_msbuild/nbgv_parity.py <fresh-directory>` pins
Nerdbank.GitVersioning 3.10.94 and its archive SHA-256. It uses the real package to
capture `NBGV_PropertyItems`, then writes a test adapter overriding
`InvokeGetBuildVersionTask`. The original package still generates assembly
attributes and ThisAssembly. Cloud-build side effects are disabled in this fixture.
The compile sandbox receives no Git repository.

On Ubuntu 22.04 ARM64, SDK 10.0.400, Bazel 9.2.0, all eight cases passed:
initial, unchanged, new commit, branch switch, explicit public release, policy
edit, inherited policy, and deleted-producer disk-cache recovery. Each build
case compares version output and exact reference-assembly bytes with raw MSBuild.
Recovery removes both the raw Git checkout and first Bazel output base, relocates
inputs and uses a fresh user root; the assembly action hits disk cache.
See [recorded results](nbgv-parity-evidence.json).

Run after building ExplicitBuild, with RULES_MSBUILD_DOTNET_ROOT,
RULES_MSBUILD_BAZEL and RULES_MSBUILD_REPOSITORY_CACHE configured.

## Boundary

This is a parity fixture, not a shipped `nbgv_version` rule or workspace-status
bridge. Its capture/adapter writer is test scaffolding. Production context-schema
validation, freshness integration, worktree/packed-ref/path-filter/shallow-history
controls and other NBGV releases remain unqualified. Disk-cache recovery does not
constitute an HTTP remote-cache test. Adapter authors must pin the package target
contract; arbitrary late imports have the same responsibility as other declared
MSBuild logic and cannot be presumed semantically compatible with every package.
