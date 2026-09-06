# Managed binary package findings

The [contract](binary-package-plan.md) and black-box e2e test were committed
before implementation. The initial run failed with `unrecognized arguments:
--binary-package-probe` (one test, 0.077 seconds).

## Implementation

`binary_inputs.py` builds repository-authored Spike.Binary and Spike.Leaf packages
outside actions with SDK 10.0.100. Each archive includes a reference assembly and
an executable assembly. Shared references Spike.Binary, which depends on
Spike.Leaf. App calls through Shared and executes both package implementations.

The existing package staging verifier now accepts a prepared archive inventory
in addition to the original checked-in build-package pins. Restore manifests
still enumerate and hash-check every resolved package payload. The runner,
replay plugin, action request and bundle schemas are unchanged.

The probe exercises the scheduling/cache matrix, fresh execution at new paths,
direct and transitive upgrades, DLL hash/deps.json evidence and rejection controls.
The generated package archives are hashed during preparation; they are not
independently pinned external artifacts. Repeated preparation of the unchanged
Leaf package at separate paths must produce identical archive bytes.

## Local validation

Pinned tool checks passed. All three package variants built, including the
unchanged Leaf archive comparison. Restore and ordinary traversal Build passed;
the baseline printed `shared-v1/binary-v1/leaf-v1/app-v1`.

Command (with SPIKE_DOTNET_ROOT/SPIKE_BAZEL pointing at the existing pinned tools):

```sh
python3 -m unittest discover -s tests/e2e -p test_binary_packages.py -v
```

The first local integration run stopped before any Bazel action because the
Java trust store could not validate bcr.bazel.build's TLS certificate. Retrying
the same prepared cold build with the system Java trust store resolved registry
access, but this container does not register Bazel's required `linux-sandbox`
strategy. No fallback strategy was used. This is not a passing sandbox/cache
result. CI validation is tracked on PR #2.

## Limits

This slice covers managed net10.0 ref/lib assets and an exact transitive package
dependency on the explicit two-project graph. It does not establish RID-specific
or native package selection, analyzers, arbitrary feeds/build targets, central
package management, version conflict behavior, full runtime closure, remote
caching or cross-platform artifact reuse. Graph export remains deferred until
the binary-package acceptance test passes in a native sandbox.
