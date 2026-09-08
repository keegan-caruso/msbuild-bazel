# Deterministic CI support contract

The supported target is deterministic CI builds. For each qualified project,
configuration and operation, the same declared inputs must produce equivalent
discovery results and reproducible artifacts across fresh execution and cache
recovery. Support remains limited to slices with linked acceptance evidence.
This document defines the requirement; it does not establish portfolio-wide
support or enable preparation reuse.

## What deterministic CI requires

- Pin source, SDKs, tasks, generators, packages and the applicable runtime/tool
  closure. Declare properties, Git/version state, environment and other inputs
  that can affect evaluation or artifacts.
- Supply meaningful build dates, version IDs and generation timestamps as
  explicit inputs, using upstream controls where available. Keep their values
  stable for reuse and invalidate affected discovery/actions when they change.
  A per-run ID is allowed, but intentionally limits reuse between runs.
- Establish and validate a file timestamp policy for staged inputs and recovered
  outputs. It must preserve required MSBuild incremental work and any observable
  file-metadata contract. Copy time must not silently become a missing input.
- Qualify each cached operation with ordinary MSBuild parity under the same
  declared inputs, repeated fresh executions, cache recovery and input-change
  controls. Record which artifacts require byte equality and which observations
  use a defined equivalence rule.

Running on a CI service, setting `ContinuousIntegrationBuild=true`, or enabling
compiler determinism does not by itself satisfy this contract. A custom target
or generator can still read the current date. `SOURCE_DATE_EPOCH` controls only
tools that honor it; it does not replace `DateTime.Now`. Giving every file the
same timestamp can also change MSBuild up-to-date decisions.

## Time-dependent projects

The [portfolio source audit](project-time-audit.md) identifies concrete cases and
their operation boundaries. Azure SDK has an explicit `OfficialBuildId` input;
Arcade supports an explicit build ID or deterministic timestamp in its relevant
versioning branch. These are candidates for qualification, not accepted adapter
configurations merely because an override exists.

Where wall-clock reads affect evaluation or output and no deterministic upstream
configuration is qualified, that operation is outside supported cache/reuse
coverage. Reject reuse or keep the operation uncached until its contract is
implemented and tested. Fresh preparation alone cannot make a time-dependent
build action safe to reuse. Do not remove upstream metadata or generation steps
to obtain a passing result.

Runtime application clocks, test timeouts, certificate validity and service
lifecycle behavior have separate Test/Launch/restore contracts. They do not
automatically disqualify a deterministic Build. Test results and running services
remain uncached under the current plan.

## Qualification gates

R09 preparation reuse and later portfolio promotions must:

1. Record the selected operation's time inputs and its file timestamp policy.
2. Show equal declared inputs preserve evaluated inputs/edges and required
   artifacts across fresh executions and cache recovery, despite permitted
   ambient differences.
3. Change each declared time/version input and demonstrate affected preparation
   or action invalidation with ordinary MSBuild parity.
4. Retain a negative control where equal content keys produce different timestamp
   observations; an ineligible operation must not reuse that result.

This is a caller/build contract plus an adapter eligibility requirement. Static
source matching cannot detect every clock read. Enforcement, accepted upstream
configurations and platform evidence must be recorded separately before claiming
support. Local reproduction can exercise the same CI contract without expanding
the compatibility claim to arbitrary developer workspaces.
