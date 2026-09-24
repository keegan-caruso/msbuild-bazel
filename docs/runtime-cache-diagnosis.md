# Runtime cache-miss diagnosis

The aborted raw-timing follow-up did not use the qualified Bazel version.
Apple Container's `exec -e RULES_MSBUILD_BAZEL=/tmp/bazel-9.2.0` retained the image's
existing value, `/opt/rules_msbuild-toolchain/.tools/bin/bazel`, which is **8.4.2**.
The output base's Java log confirms `Build label: 8.4.2`. The successful seed's
build-event log records **9.2.0**. Both executables were checked directly.

The resulting SDK canonical repository path changed from
`+local_dotnet_sdk+dotnet` to `+_repo_rules+dotnet`. This changes declared input
paths, generated requests and worker tool manifests across the graph. The cache
misses were caused by the benchmark selecting another Bazel version; they do not
establish a cache eviction or artifact-integrity failure.

## Fix and checks

Set overrides with `env` inside the container command:

```sh
container exec runtime-closure-producer env \
  RULES_MSBUILD_BAZEL=/tmp/bazel-9.2.0 \
  python3 /work/rules/tests/explicit_msbuild/runtime/leaf_timing.py \
  WORKSPACE OUTPUT_BASE REPORT --cache CACHE_URL
```

Both timing harnesses now verify SDK 10.0.400 before building. The Bazel harness
also checks the executable's actual version (9.2.0 by default), then records its
path and SHA-256 in `toolchain.json`. A negative control rejects the image's
8.4.2 executable before a build starts. `--expected-bazel` permits an explicitly
selected alternate version; filenames alone are not version evidence.

With verified 9.2.0, the same output base recovers the original baseline with
**zero managed/native compilations**. All six unique edits compile only Pipelines;
all no-ops and source restorations compile nothing. Public reference bytes remain
unchanged and original implementation bytes are recovered after restoration.

| Verified Bazel mode | No-op median | Body-edit median | Edit samples |
| --- | ---: | ---: | --- |
| Batch | 5.446 s | 9.691 s | 9.530 / 9.776 / 9.691 s |
| Retained server/worker | 0.166 s | 3.495 s | 4.955 / 3.495 / 3.434 s |

The first retained-worker edit starts the compiler worker. The later two warm
edits take 3.43–3.50 seconds. Compared with the separately recorded raw shared-
compiler median of 11.274 seconds, the corrected Bazel median is **3.23× faster**.
The [raw comparison's scope limits](runtime-leaf-timing.md) still apply.

See [recorded evidence](runtime-cache-diagnosis-evidence.json). Full profiles and
logs are retained at `/private/tmp/corrected-leaf-timing.tar.gz`. The container's
unreaped-server shutdown issue still occurs after measurement; it is excluded
from every sample. No cache keys or production execution rules were weakened.
