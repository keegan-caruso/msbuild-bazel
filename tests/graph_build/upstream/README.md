# Source-runtime body-edit trial

`runtime_source_trials.py` is a qualification harness for five Pipelines body
edits in an independently qualified, complete Linux ARM64 source-runtime
product. It requires a fresh input-only closure created by
`runtime_product_recovery.py` and uses `runtime_recovered_tests.py` to
construct reviewed edits and inspect execution logs. The baseline is reported separately from the five cycles. This
is not an API/native rebuild benchmark, a raw MSBuild comparison, or evidence of
performance until the trial is actually run.

The production rules and the harness are separate inputs. For the current trial,
freeze the planned public production revision
`78d23538474b500c616af3c2e9b3778dbd19ee9a`; its complete product
qualification must pass before these trials; use the reviewed harness commit
containing this file, and record both its commit and this file's SHA256. Do not
substitute an unreviewed checkout as the product oracle. The product workspace,
its SDK 11.0.100 graph, the exact qualification mappings and their independently
verified SHA256, and a strict `runtime_test` JSON from the independent qualified
product must already exist. A healthy shared AC/CAS endpoint containing the
product’s seeded Bazel actions and the Ubuntu 26 ARM64 worker environment are
also required. Project-cache
read-only mode does not publish project snapshots; the separately reported,
timing-excluded baseline must populate the local project cache before scored
cycles. The harness does not upload Bazel actions or project snapshots. Use a
fresh workspace and empty output base on guest-local storage, with enough disk
and memory for the complete product.

For example, place the frozen production checkout at `$TRIAL_ROOT/rules`, with a
separate checkout containing this harness in `$HARNESS`, and set the remaining
variables to the independently verified inputs before running. The harness uses
its process environment rather than a source-runtime `setup.json`; set
`RULES_MSBUILD_DOTNET_ROOT`, `RULES_MSBUILD_BAZELISK` and `BAZELISK_HOME` to the
qualified guest tools and Bazel cache, and set `RULES_MSBUILD_PROJECT_CACHE_URL`
to the verified endpoint. Do not rely on an ambient host SDK or Bazel default:

```sh
git -C "$TRIAL_ROOT/rules" rev-parse HEAD
sha256sum "$HARNESS/tests/graph_build/upstream/runtime_source_trials.py"
python3 "$TRIAL_ROOT/rules/tests/graph_build/upstream/runtime_product_recovery.py" \
  close "$PRODUCT_WORKSPACE" "$TRIAL_ROOT/workspace"
export RULES_MSBUILD_PROJECT_CACHE_URL="$READ_ONLY_CACHE_URL"
python3 "$HARNESS/tests/graph_build/upstream/runtime_source_trials.py" \
  "$TRIAL_ROOT/rules" "$TRIAL_ROOT/workspace" "$TRIAL_ROOT/output-base" "$RESULTS" \
  --qualification-mappings "$VERIFIED_MAPPINGS" \
  --expected-mappings-sha256 "$VERIFIED_MAPPINGS_SHA256" \
  --oracle "$INDEPENDENT_RUNTIME_TEST_JSON" \
  --revision 78d23538474b500c616af3c2e9b3778dbd19ee9a
```

Verify the first command equals the stated production revision and compare the
harness digest with the reviewed harness artifact before running; `--revision`
is recorded in results and does not perform that check. The closure helper
rewrites its rules override to `../rules`, so the workspace and frozen rules
checkout must be siblings as shown, or that override must be independently
validated against the supplied rules checkout. Results and output base must be
fresh and outside the workspace. The harness checks reviewed edit inputs against the closure manifest, the existing
qualification exemption, independent baseline binary hashes, forced tests,
source implementation/reference hashes and stable worker identities. It restores
edited files and their original modes/timestamps after the run. Its summary and
raw logs belong outside Git; a failed assertion is a failed qualification, not a
measurement.
