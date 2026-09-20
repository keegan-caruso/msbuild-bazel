# Linux hardened-worker capability probe

Apple Container runs the Linux-specific worker qualification locally; GitHub CI
is not required for this probe. Current host verification: Apple Container 1.4.1,
service running. Tested guest: Linux ARM64, .NET 10.0.400, Bazel 8.4.2, toolchain
image `sha256:47a9e2fed01824f5470f26e75a2fb74017acc1967c637e7793be028f31a8aeee`.
This does not establish x86-64 or macOS worker behavior.

`tests/remote_workers/linux_hardened_worker_probe.py` creates an actual JSON
persistent worker and runs two separate Bazel builds with one worker instance.
It enables `--worker_sandboxing`, `--experimental_worker_sandbox_hardening` and
`--sandbox_fake_username`, with an explicit blocked path. The fixture is Python
only because it tests the Bazel protocol and sandbox; it is not a production
MSBuild worker implementation or a compiler performance measurement.

| Check | Observed |
|---|---|
| Process reuse | Same PID; request counter advances from 1 to 2 |
| Declared inputs | Both requests read their own expected content |
| Prior request's undeclared relative input | Unreadable |
| Explicitly blocked path | Unreadable with fake/non-root sandbox identity |
| Write outside worker workspace | Denied, even into a guest directory with mode 0777 |
| Connect to guest host loopback listener | Denied; parent connection control succeeds |
| Absolute undeclared file elsewhere in guest | **Readable** |

The last result is a real limitation. Hardened workers do not by themselves
replace our input-read allowlist. Preserve or implement that boundary before
integrating the persistent MSBuild/compiler path or treating inputs as an
immutable cross-action validation contract. A passing protocol probe is not
production worker/cache qualification.

## Layout and identity constraints

Use pre-created guest-local Bazel state under `/workspace`. Placing worker state
under `/tmp` failed: the private temporary mount hid the inaccessible-path helper
needed for a bind mount. Bazel 8.4.2's SandboxedWorker implementation explicitly
notes this layout constraint. Running as guest root also permitted opening the
permission-masked blocked file; the non-root sandbox identity rejected it.
The probe therefore supplies that identity explicitly.

Reproduce from the checkout:

```sh
RULES_MSBUILD_CONTAINER_IMAGE=rules_msbuild-toolchain:arm64 \
  bash scripts/run-apple-container.sh \
  python3 tests/remote_workers/linux_hardened_worker_probe.py /evidence
```

The launcher mounts source read-only, copies it into the guest, validates tool
pins, and removes the container afterward. It uses the existing documented Apple
Container nested-sandbox options. Logs remain under the printed evidence directory;
this run used `artifacts/apple-container/run.i1FHwM`. The checked-in JSON preserves
the assertions and measured absolute-read limitation. Toolchain/Starlark checks,
Python syntax and diff whitespace checks passed. No CI ran.
