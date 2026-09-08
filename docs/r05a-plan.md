# R05a: generator delivery, reference roles and diagnostics

Fixture acceptance is complete on native macOS ARM64: 35 probe cases across the
three matrices. The Spectre.Console real-project gate remains outstanding on
SDK/framework/package prerequisites. See [measured findings](r05a-findings.md).

## Acceptance contract

The selected Release/net10.0 consumer must match ordinary MSBuild when its graph
contains ordinary library, analyzer-only and build-order-only references. Classic
and incremental generators run in fresh compiler processes. A package generator
and project generator must operate together. A diagnostic-only analyzer must be
qualified through project and package delivery, including severity, suppression and
warnings-as-errors. Dependency frameworks follow SDK negotiation.

Build actions retain MSBuild compilation and strict dependency replay. Restore and
package acquisition occur during preparation. Preparation must not compile graph
producers. Every acceptance run removes preparation sources before sandbox builds.

Required evidence:

1. Ordinary-MSBuild behavior, compiler roles, runtime files and diagnostics.
2. Cold native sandbox executions, unchanged reuse and exact mutation action sets.
3. Independent generator, additional-file, configuration and diagnostic mutations;
   removing input cannot leave generated behavior behind.
4. Missing/corrupt generator input rejection and explicit generator failure.
5. Producer-free relocated disk-cache recovery, followed by a new consumer source
   edit forcing compilation with recovered generators/analyzers.
6. Selected framework identities and reference roles in a mixed graph.
7. A pinned Spectre.Console slice with unchanged project declarations and an
   additional-file behavioral oracle.

The initial required platform is native macOS ARM64. Linux ARM64 qualification is
separate; Linux x86-64 CI remains deferred. Interceptors, the full CommunityToolkit
framework matrix, Pack, remote workers and performance at scale are outside scope.

## Delivery order

Establish fixture oracles; preserve restore/reference semantics; validate project
handoff; add package combination and diagnostic-only controls; validate configured
references and recovery; qualify the real-project slice. Record actual commands,
results and limitations in a linked findings document. This contract is proposed
acceptance, not a claim that all cases pass.
