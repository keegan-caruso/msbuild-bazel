# Orchard action-local cache publication and upload overlap

The opt-in direct-cache mode now uses Bazel background uploads. The default
whole-workflow publication gate is unchanged. Direct mode retains producer bundle
validation, verified downloads, the concurrent-input-change guard and controller
leases. It publishes successful actions independently; a later test or workflow
failure does not retract earlier valid action entries.

In Bazel 8.4.2, [RemoteExecutionService.shutdown](https://github.com/bazelbuild/bazel/blob/8.4.2/src/main/java/com/google/devtools/build/lib/remote/RemoteExecutionService.java)
waits for the background task phaser before releasing the cache. The
[RemoteModule](https://github.com/bazelbuild/bazel/blob/8.4.2/src/main/java/com/google/devtools/build/lib/remote/RemoteModule.java)
registers this cleanup through the blocking command-completion module. Thus
uploads can overlap subsequent actions while command completion still waits for
them. This is asynchronous cache upload, not remote execution.

The full-graph probe uses the same 202-project Orchard source, state path and
validation settings in both modes, with a separate empty cache per mode. Package
archives and repository downloads are warm. Both fresh runs must compile all 202
projects without remote action hits. Independent producers retain the documented
Razor build-path variation; exact byte parity is required for producer recovery.
The direct producer is then shut down and deleted before a read-only fresh-state
recovery. Recovery must execute no compilation, restore, discovery, package
extraction or binding, retain no extracted package payloads, and serve the C#,
Razor and CSS runtime markers.

This is a same-host loopback cache experiment, not a WAN or remote-execution
measurement. Cold workflow time includes preparation and publishing, whereas raw
MSBuild does not create or upload equivalent cache artifacts.

## Measured results

| Case | Seconds |
|---|---:|
| Gated fresh build | 585.023 |
| Direct fresh build with upload overlap | 574.434 |
| Direct producer-deleted recovery | 27.875 |
| Gated fresh-state recovery | 27.700 |

Each fresh run executed 202 compilations, 202 bindings, one restore/discovery and
287 package extractions, with no remote action hits. Both recovery runs executed
none of these actions, downloaded no extracted package payloads, and passed the
C#, Razor and CSS HTTP checks. Direct recovery reproduced all 3,457 producer
application files byte for byte after producer state was removed.

The 61.0s final publication phase disappears, but the end-to-end reduction is only
10.6s (1.8%) in this single pair. The package phase ends at 61.8s rather than 35.2s;
the compilation interval is 379.1s rather than 357.6s. The trace contains uploads
throughout compilation, ending before composition finishes. Upload work is
redistributed, not eliminated. This does not isolate asynchronous upload from
removing the gate: the two complete publication paths are being compared, using
their existing transport/concurrency defaults. Short trace events are merged, so
trace event counts are not action counts.

Independent fresh builds have identical 3,457-file membership, with 156 differing
files (78 DLL/PDB pairs). Three inspected assemblies have identical IL across
1,332 methods; their changed PDB document checksums belong to Razor-generated
sources. This is consistent with the previously documented independent-build
Razor variation, not proof of full semantic or byte equivalence. The initial
strict comparison caught this difference and stopped; recovery was then qualified
separately using the retained cache stores. The probe now records independent
DLL/PDB-pair differences explicitly while requiring exact producer-recovery parity.

The four-project native acceptance and valid/invalid action publication retry
controls also pass with asynchronous uploads. Keep direct mode opt-in: these
results do not establish a meaningful cold-build win or justify changing the
whole-workflow publication contract. Raw data is under
`/private/tmp/action-upload-orchard`; the paired probe is
`tests/remote_workers/orchard_publication_probe.py`. See the accompanying evidence.

Final checks: all 69 applicable workflow tests passed (one Linux-only skip),
action-runner tests passed, all owned tools built with warnings as errors, and
C# formatting, Python syntax and whitespace checks passed. The raw comparator
also served the same C#, Razor and CSS runtime markers.
