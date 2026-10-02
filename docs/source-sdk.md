# SDK from source

Historical producer qualification: dotnet/dotnet revision
`b0f34d51fccc69fd334253924abd8d6853fad7aa`, Ubuntu 22.04 ARM64, Bazel 9.2,
source-built SDK 10.0.100. The pin in `tests/source_sdk/pin.json` records source,
bootstrap artifacts, native prerequisites and reviewed upstream definitions.

MSBuild evaluates RepositoryReference/ProjectReference conditions, then Bazel
schedules 22 source component actions. The SDK action declares both its archive
and expanded SDK layout. It emitted 4,786 files and built/ran a library/app consumer
on its produced runtime. A fresh same-machine consumer recovered all 31 logged
actions, including 22 components, with uploads and disk cache disabled. Recovered
SDK bundle hash: `b9c79ae5393fc5215af934bfa75fa10af7b35c9248e42ced6aa044a0e16937f6`.

Producer rules keep the declared bootstrap SDK, sources, native archives and
upstream build scripts separate from the produced SDK. Consumers now use graph
rules and [the shared SDK contract](sdk-toolchains.md). Full producer/consumer
qualification has not been repeated after the graph-only cutover. Old Pack/Razor/
Publish/NoTargets observations are at [the pre-cutover revision](history.md).

## Reproduce

```sh
python3 tests/source_sdk/inventory.py --help
python3 tests/source_sdk/evaluate_graph.py --help
python3 tests/source_sdk/source_action_prepare.py --help
python3 tests/source_sdk/component_graph_prepare.py --help
python3 tests/source_sdk/component_consumer_probe.py --help
python3 tests/source_sdk/package_handoff.py /tmp/fresh-package-handoff
```

Use pinned source/bootstrap/native inputs and fresh output directories in the
qualified Ubuntu ARM64 environment. Component producers need substantial disk
space; do not count partially cached seed time as a matched cold build score.

## Limits

One source revision/architecture, isolated local component actions, no RBE claim.
No matched full cold component graph versus raw build exists. A repeat isolated
build with identical declared inputs differed in 301/5,149 payload files; cause
unresolved. Self-hosting changed bootstrap inputs and is also not byte-identical.
HTTP recovery reuses a recorded output; it does not prove independent reproducibility.
Trimming, arbitrary workloads and graph-native AOT need separate qualification.
