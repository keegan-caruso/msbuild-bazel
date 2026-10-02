# Linux graph workers

The persistent graph process is a cache/preparation broker. Each request starts a
fresh MSBuild process inside a stable Bubblewrap filesystem. It does not retain
mutable evaluated projects across builds.

```starlark
app_graph(name = "graph", linux_stable_paths = True, linux_worker = True)
```

```sh
bazel build //:graph --strategy=MSBuildGraph=worker --worker_sandboxing \
  --worker_max_instances=MSBuildGraph=1
```

Stable paths isolate workspace, SDK, runner, packages and scratch. The inner
namespace has its own PID namespace and `/proc`. The graph cache transport retains
network access; project isolation is not a claim that arbitrary custom tasks are
filesystem-hermetic. Reviewed task/input declarations remain required.

Bazel's `--experimental_use_hermetic_linux_sandbox` can be combined with worker
sandboxing in the qualified Linux VM. Strict native-sandbox byte/mode parity and
worker recovery were checked on Bazel 8.8/9.2. The outer VM must allow nested
user/mount/PID namespaces, include Bubblewrap, and expose appropriate `/proc`/`sys`
mounts. Normal Docker defaults may prevent this. See
[Apple containers](apple-container-runbook.md).

`worker_cache_mb` controls conservative logical cache bytes, default 4096; zero
discards between requests. Eviction causes rebuilds, not missing outputs. It is not
a process-memory cap. `profile_build` is false by default; enable it only for separate
diagnostic requests.

Checks:

```sh
python3 tests/graph_build/linux_worker.py --bazel-version 8.8.0
python3 tests/graph_build/linux_worker.py --bazel-version 9.2.0
python3 tests/graph_build/linux_prepared_restore.py
python3 tests/graph_build/linux_bazel_remote.py --graph-worker --help
```

Evidence is Linux ARM64. Linux x86-64, macOS persistent workers and RBE require
independent qualification. [Performance](performance.md) separates whole-action,
local project and independent HTTP recovery.
