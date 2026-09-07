# Lessons from Bazel language rules

Research snapshot: 2026-09-07. This document compares Java, Scala, Python,
TypeScript, Go and Rust rules with this repository's MSBuild-retention goal.
It records design lessons and proposed experiments, not new implementation or
acceptance evidence. Upstream links describe evolving rulesets; they do not
establish behavior for every release or configuration.

## Architectural comparison

The adapter retains MSBuild project execution while Bazel schedules and caches
configured projects. Most rules below instead construct compiler or runtime
actions directly. Importing an ecosystem's manifests is distinct from retaining
its build orchestrator and arbitrary extensions.

| Ecosystem | Bazel boundary | Existing ecosystem integration | Lesson for this adapter |
| --- | --- | --- | --- |
| Java | Compiler and supporting tool actions | Java toolchains and Maven artifact integration | Separate compile interfaces, implementations, runtime files and plugins. |
| Scala | Scala/JVM compilation actions | Scala toolchains, compiler plugins and JVM dependencies | Model executable compiler dependencies and exceptions to interface-only consumption. |
| Python | Libraries, runtime assembly, tests and optional bytecode compilation | Locked PyPI dependencies and interpreter toolchains | Separate acquisition from execution and describe runtime files explicitly. |
| TypeScript | Project type-checking, declaration generation and transpilation | Real TypeScript compiler and tsconfig, within Bazel's output contract | Preserve compiler configuration while making outputs predictable. |
| Go | Package compilation and linking | Gazelle generates targets and integrates module dependencies | Reuse graph discovery and make configured package dependencies explicit. |
| Rust | Crate compilation, build scripts and procedural macros | Cargo manifests/lockfiles can generate Bazel dependencies | Distinguish ordinary dependencies from code executed during the build. |

Our [graph rule](../bazel/graph.bzl) currently publishes a directory bundle and
passes all reachable dependency bundles into each consumer action. The bundles
contain artifacts and normalized MSBuild target-result metadata. Consumers replay
those results so MSBuild does not rebuild dependencies. The
[replay findings](replay-findings.md) explain why raw MSBuild caches were not a
portable substitute.

This compatibility layer is the main additional responsibility compared with
direct compiler rules. Keeping MSBuild remains the design goal.

## Java: narrow the compile-time contract

Java's `JavaInfo` separates compile-time JARs, full JARs, runtime artifacts and
plugin information. Compile-time artifacts can be interface JARs, allowing
consumers to avoid depending on implementation bytes when interfaces suffice.
API-generating annotation processors are explicitly represented because their
outputs affect header generation.

Sources: [JavaInfo](https://bazel.build/rules/lib/providers/JavaInfo) and
[Java compilation tools](https://bazel.build/docs/bazel-and-java).

For .NET, reference assemblies are the closest analogue. A candidate contract
would distinguish reference assemblies, implementation/runtime files, executable
build tools and replay metadata. This is a proposal; the current bundle provider
does not provide that separation.

For Shared -> App, a Shared method-body edit can change its implementation while
leaving its reference assembly unchanged. Today the changed bundle invalidates
App's project action. MSBuild may skip compilation inside that action, but that
is different from Bazel reusing the action itself.

Splitting provider fields alone would not fix this: any action still consuming
the complete bundle remains sensitive to all its bytes. Compile and runtime
staging inputs must be separated, and replay metadata must not accidentally
reintroduce implementation hashes into the compile boundary. Custom targets that
inspect implementation assemblies need an explicit broader contract.

## Scala: interface boundaries need qualified exceptions

Scala rules expose compilation, compiler plugins, dependency tracking and
persistent workers. The Scala library documentation describes interface JARs,
while JavaInfo explicitly acknowledges Scala cases requiring full compile-time
JARs. Interface-only consumption is therefore a capability to qualify, not a
universal assumption.

Sources: [Scala rules and workers](https://github.com/bazel-contrib/rules_scala),
[Scala library](https://github.com/bazel-contrib/rules_scala/blob/master/docs/scala_library.md)
and [full compile-time JARs](https://bazel.build/rules/lib/providers/JavaInfo#full_compile_jars).

For this adapter, ordinary references, analyzers, source generators and MSBuild
tasks need distinct roles. A generator or task executes implementation code and
may load additional dependencies. A reference assembly alone cannot satisfy that
role. Role selection must preserve MSBuild/NuGet semantics, including transitive
behavior, rather than impose another language's strict-dependency policy.

Persistent workers suggest a later startup-cost experiment. They do not remove
the need to declare tools and inputs or prevent state leaking between requests.
A persistent Bazel server, an MSBuild node and a C# compiler server are different
mechanisms and should be measured separately.

## Python: acquisition and runtime assembly are separate contracts

Python rules integrate locked PyPI dependencies, interpreter selection and
platform-specific wheels. Bytecode precompilation is optional; ordinary Python
source consumption is not equivalent to a .NET compiler action.

Sources: [PyPI integration](https://rules-python.readthedocs.io/en/latest/pypi/download.html),
[Python toolchains](https://rules-python.readthedocs.io/en/latest/toolchains.html)
and [precompilation](https://rules-python.readthedocs.io/en/latest/precompiling.html).

Our Restore/preparation versus build-action separation follows a similar
principle. Reusable prepared inputs should capture resolved package content and
configuration without relying on ambient package caches. NuGet packages can also
import targets and execute build tools, so acquisition alone does not establish
their complete action-input contract. Python source distributions and native
wheels likewise require more than a pure-source runtime model.

The existing [multi-language harness](multilanguage-findings.md) already records
Python-only edits rerunning tests without recompiling .NET or TypeScript, and
actual recovered-program execution. That is local composition evidence, not a
cross-language compiler benchmark or proof of remote execution correctness.

## TypeScript: retain configuration, declare outputs

Aspect's rules_ts uses the real TypeScript compiler and tsconfig configuration,
with validation and constraints needed for Bazel's declared outputs. It supports
separating JavaScript transpilation from type-checking and declaration generation.
This preserves compiler configuration without preserving arbitrary npm scripts
or every existing project orchestration workflow.

Sources: [rules_ts overview](https://github.com/aspect-build/rules_ts),
[tsconfig integration](https://github.com/aspect-build/rules_ts/blob/main/docs/tsconfig.md)
and [transpiler design](https://github.com/aspect-build/rules_ts/blob/main/docs/transpiler.md).

Type declarations are analogous to reference assemblies; JavaScript is analogous
to executable implementation artifacts. Where declarations form the dependency
boundary, type-checking can avoid consuming implementation files. The exact
benefit depends on rule configuration and inputs.

For MSBuild, retain project evaluation while requiring explicit contracts for
generated sources, outputs and custom tasks. Unknown output behavior should be
qualified or rejected, rather than silently omitted from the Bazel action model.
Any future separation of compilation and staging must preserve observable SDK
target ordering and behavior.

## Go: reuse graph generation and model configurations

rules_go invokes the Go compiler and linker directly. Bazel and rules_go assume
the orchestration role normally held by the go command. Gazelle generates BUILD
dependencies, and its module integration can use go.mod to establish external
dependencies. The resulting Bazel targets drive execution.

Sources: [rules_go architecture](https://github.com/bazel-contrib/rules_go#can-i-still-use-the-go-command),
[Go providers](https://github.com/bazel-contrib/rules_go/blob/master/go/providers.rst)
and [Gazelle module integration](https://github.com/bazel-contrib/bazel-gazelle/blob/master/extensions.md).

The transferable lesson is a reusable discovery boundary. Our exported configured
graph should remain valid until its actual discovery inputs change. Project
identity must still include global properties and framework selections; project
path alone is insufficient. Source additions, removals and changed imports need
invalidation even when previously enumerated source files have unchanged content.

Go also makes platform selection and cgo toolchains explicit. The corresponding
.NET concern is distinguishing the platform executing SDK/tasks from the target
framework, RID and native toolchain of the produced application. Go package
archives/export information should not be assumed to have Java-style public-API
stability under every implementation edit.

## Rust: make build-time execution a first-class dependency role

Crate Universe can use Cargo.toml and Cargo.lock to generate dependencies for
Bazel Rust rules. Normal compilation uses rustc actions. cargo_build_script
models build scripts with declared dependencies, tools, data and environment;
procedural macro dependencies are distinguished from ordinary crate dependencies.

Sources: [Crate Universe](https://bazelbuild.github.io/rules_rust/crate_universe_bzlmod.html),
[build scripts](https://bazelbuild.github.io/rules_rust/cargo_build_script.html)
and [Rust rule implementation](https://github.com/bazelbuild/rules_rust/blob/main/rust/private/rust.bzl).

| Rust concept | Useful .NET analogy |
| --- | --- |
| Ordinary crate dependency | Assembly reference |
| Procedural macro | Generator/analyzer executing during compilation |
| Build script | Custom generation or native-build task |
| Build-script environment and outputs | Declared task inputs, generated files and result metadata |

These are analogies, not equivalent semantics. Rust models selected Cargo
behavior explicitly; this adapter retains MSBuild to execute its behavior.
The useful lesson is to declare executable dependencies and their supporting
files separately from ordinary references, including execution-platform needs.

Rust also supports metadata-based compilation pipelining in eligible cases.
Earlier availability of metadata can shorten the critical path without making
that metadata invariant under implementation edits. Pipelining, action-cache
reuse and incremental work inside a compiler are separate benefits. Reference
assemblies should be evaluated with the same distinction.

## Proposed experiments and priorities

The [active execution order](roadmap.md#active-execution-order) schedules
preparation reuse alongside R05, with compile-boundary optimization after the
relevant R05/R06 contracts. The table below groups design priorities rather than
imposing serial execution. No experiment marks existing gates complete or
changes the MSBuild-retention direction.

| Priority | Experiment | Required evidence |
| --- | --- | --- |
| 1 | Qualify reference, generator, analyzer and task roles alongside R05/R06. | Mutate each tool and supporting dependency; require affected work to rerun. Reject missing inputs. Match ordinary MSBuild behavior. |
| 2 | Reuse graph export and preparation when discovery inputs are unchanged. | Source additions/removals, imports, restore changes and configuration mutations invalidate correctly. Relocation and producer deletion still work. |
| 3 | Introduce a qualified compile-interface versus runtime-staging boundary. | A Shared implementation-only edit leaves App compilation reusable while execution observes the new implementation. An API edit invalidates compilation. Custom implementation-reading tasks remain correct. |
| 4 | Make SDK/tool execution and target platform selection explicit. | Unsupported combinations fail clearly; platform/tool changes affect identity. Preserve current local-only restrictions until independent-worker qualification. |
| 5 | Evaluate workers or earlier reference publication after profiling. | Separate startup, preparation, compilation and staging times; check state isolation and memory. Do not infer speedup from fewer compiler invocations. |

The existing [Serilog measurements](serilog-performance-findings.md) support
prioritizing preparation: the unchanged case records median export of 0.573 s,
preparation of 3.091 s and Bazel Build of 0.564 s. Those are three-repetition,
two-project macOS measurements with disclosed shared compiler/host state, not a
scale forecast. Test execution is timed separately.

For every experiment, distinguish a skipped compiler task from an unexecuted
Bazel action, and a cached test result from actual program execution. Preserve
the [validation strategy](validation.md), native sandbox requirements and
producer-free relocation controls. None of these upstream designs establishes
full runtime closure, remote-cache correctness or cross-platform artifact reuse
for this adapter.
