# Source-runtime body-edit trial

`runtime_source_trials.py` qualifies five Pipelines body edits in an independently qualified Linux ARM64 source-runtime product. It needs a fresh input-only closure (`runtime_product_recovery.py`) and uses `runtime_recovered_tests.py` for reviewed edits and log inspection. Baseline is reported separately from the five cycles. Not an API/native rebuild benchmark, raw MSBuild comparison, or performance evidence until run.

Production rules and harness are separate inputs: freeze production revision `78d23538474b500c616af3c2e9b3778dbd19ee9a` (complete product qualification must pass first), use the reviewed harness commit containing this file, and record its commit and SHA256. Never substitute an unreviewed checkout as the oracle. Prerequisites: qualified product workspace, SDK 11.0.100 graph, exact qualification mappings + verified SHA256, strict `runtime_test` JSON oracle, healthy shared AC/CAS with seeded Bazel actions, Ubuntu 26 ARM64 worker, and fresh workspace + empty output base on guest-local storage with sufficient disk/memory. Because project-cache read-only mode does not publish snapshots, the timing-excluded baseline must populate the local project cache before scored cycles; the harness never uploads Bazel actions or project snapshots.

Place frozen production rules at `$TRIAL_ROOT/rules` and harness checkout at `$HARNESS`. Set `RULES_MSBUILD_DOTNET_ROOT`, `RULES_MSBUILD_BAZELISK`, `BAZELISK_HOME` (guest tools/cache), and `RULES_MSBUILD_PROJECT_CACHE_URL` (do not rely on `setup.json` or ambient defaults):

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

Verify `rev-parse HEAD` matches the frozen revision (`--revision` only records it) and verify the harness SHA256. `close` rewrites the rules override to `../rules`, so workspace and rules must be siblings (or validate the override). `$RESULTS` and output base must be fresh and outside the workspace. The harness reads test evidence from local Bazel outputs or undeclared-outputs ZIP, verifies edit inputs against the closure manifest, qualification exemption, baseline binary hashes, forced tests, implementation/reference hashes, and stable worker IDs, and restores edited files (modes/timestamps) afterward. Keep summaries/logs out of Git; any failed assertion fails qualification.
