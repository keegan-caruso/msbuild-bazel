# Avalonia edit and Headless qualification

This continues the pinned [expanded Avalonia graph](avalonia-expanded.md).
The controls exercise dependency correctness, not performance.

The four edit/restoration controls pass on **Bazel 8.8.0 and 9.2.0**, using
the SDK-free Linux ARM64 worker. [Evidence](avalonia-invalidation-evidence.json)
records exact executed targets and negative-control failure counts.

## Edit contracts

`tests/explicit_msbuild/avalonia/invalidation.py` starts from the expanded
source-only workspace and its producer cache namespace. It makes one edit at a
time, checks the exact executed compilation/generation/test targets, and restores
the original bytes in a `finally` block.

| Input edit | Expected compilation/generation | Expected tests |
| --- | --- | --- |
| Native IDL internal enum value | Native IDL generator, Native, Desktop | None |
| Simple theme unused XAML color resource | Both configured Simple theme assemblies | All five suites |
| Corrupt rendering baseline | None | Skia rendering fails |
| Corrupt declared Fontconfig library | None | Both Skia suites fail |

The IDL changes its generated output and friend-visible reference contract.
The XAML changes the runtime assembly while preserving reference bytes. The
negative controls must produce failing test cases, not merely a failed Bazel
command. Every restoration must recover the original passing outcomes without
executing compilation, generation, or tests.

```sh
python3 tests/explicit_msbuild/avalonia/invalidation.py /path/to/expanded/bazel \
  /tmp/fresh-edit-results --executor grpc://WORKER_IP:8980
```

Set `USE_BAZEL_VERSION` to the producer's version. `--instance` can select another
producer cache namespace containing the same inputs. Use a fresh result directory;
its name distinguishes mutation bytes so earlier runs cannot cache the edit
controls themselves.
