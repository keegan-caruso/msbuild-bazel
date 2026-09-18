# Integrity streaming measurement protocol

- Profile the actual resolved SDK root used by `Host.Real`, then query its Nix
  runtime closure. The development-shell wrapper has a broader closure and is
  excluded from production measurements. The measured closure has 19 roots.
- Capture a baseline snapshot, then five profiled scans in one process. Separate
  file reading/buffering, hashing, manifest construction, canonical digesting and
  manifest comparison. Record cumulative managed allocation on the calling thread
  and GC collection counts, not peak memory. GC counts cover the whole cycle,
  including comparison and canonical digesting.
- Profile hooks are test-only opt-in parameters; normal workflow calls collect
  no per-file clocks or allocation counters. Profiling overhead and its warm
  process are not substituted for one-shot workflow timings.
- Preserve per-root canonical snapshot digests across buffered and streaming
  variants. Require identical file counts, bytes hashed, modes, symlink records,
  sizes and content digests. Do not replace verification with metadata trust.
- Implement one bounded streaming change for snapshot/worker hash-only reads.
  Keep the regular-file descriptor checks, no-follow/nonblocking opens,
  before/after metadata checks, namespace checks and exit validation.
- Validate empty inputs, buffer boundaries, a multi-buffer large file, symlinks,
  FIFOs, directories, changed contents with restored size/mtime, conflicting
  expectations and changes between validation passes.
- Then collect three unprofiled repetitions each of unchanged and body-edit
  diamond/Serilog. Keep reused Bazel installation and repository-download cache,
  fresh consumer source/preparation/server/action state, deleted producer,
  pinned real native CAS, raw comparator and exact DLL/PDB/execution checks from
  the repository-cache protocol. Do not run other builds/tests during timing.
- Compare with the immediately preceding repository-cache results. Preserve the
  adapter <= 1.25 * raw + 0.250 s diagnostic target. Report sequential-run noise
  and the unchanged same-host qualification limit. Cold/API cases are not part
  of this focused follow-up.
