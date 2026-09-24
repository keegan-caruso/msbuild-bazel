# Public repository preparation

Prepared on 2026-09-23 from main `46d7f37`, while the repository was private.
**The repository is now public; no release was created.**
The owner chose MIT licensing for original code. This is preparation for publishing
an experimental source project, not a stable version or binary-package release.

## Prepared changes

- MIT license with a separate third-party notice for the adapted Buildbarn fixture.
- Contributor and security guidance, bug-report and pull-request templates.
- README with an explicit experimental status, current installation boundary,
  runnable library/application/test example and current runtime qualification link.
- GitHub Actions pinned to verified commit IDs, retaining read-only permissions
  and manual dispatch. No workflow was started.
- Local credential-file ignores and removal of links to the private issue tracker
  from historical documents; the issue IDs remain as provenance.

## Audit results

Gitleaks 8.30.1 scanned a fresh mirror of the remote, the prepared working tree,
release assets, workflow artifacts and available workflow logs. Its downloaded
binary archive was SHA-256 verified. Reports were redacted; no scanner suppression
or broad allowlist was added. [Compact evidence](publication-audit.json) records
refs, counts, report hashes and the local evidence directory.

| Scope | Result |
| --- | --- |
| 366 reachable commits, including 26 branches, 12 PR refs and one tag | 404 alerts reviewed: 395 recorded content hashes, nine prose matches; no unresolved credential finding |
| Prepared source tree | 136 alerts reviewed: 133 content hashes, three prose matches |
| Five assets on the historical prerelease | 30 alerts reviewed: 29 hashes and one ordinary cache-name string |
| All 136 retained Actions artifacts (170 MB compressed) | No detections; archive traversal scanned about 2.97 GB of content |
| 175 available workflow-log archives | No detections |
| 73 issue/PR records, one issue comment, zero review comments | No detections |

GitHub returned HTTP 404 for 109 of 284 workflow-run log downloads. Those archives
were not inspected; a 404 is not evidence about their former contents. Signature
scanning is not proof that no secret exists and does not establish the safety of
arbitrary binary content. Recheck changed refs, issues and artifacts at launch.
Historical evidence retains local temporary paths and private network addresses;
these identify past test environments and are not usable public download URLs.

## Validation

In a clean staged source tree on Linux ARM64 / SDK 10.0.400 / Bazel 9.2.0:

- Built ExplicitBuild with warnings as errors: zero warnings or errors.
- Created the standalone example, ran the application and passed its Bazel test.
- Changed only the library message; the dependent test failed as expected.
- Passed toolchain and Starlark checks after formatting the example.
- Passed five local CI-dispatch unit tests, Python syntax and local documentation-link checks.

This does not add new Linux x64, Windows or macOS qualification. The changed CI
pins were resolved from upstream repositories; their workflows were not executed.

## Publication status and remaining follow-up

1. Preparation, docs cleanup and stricter code style are on public main at
   `772c77e`. This publishes source, without a stable release or BCR entry.
2. Decide how to present the **25 old non-main remote branches**. The historical
   GitHub release and all five attached assets were deleted at the owner's
   request on 2026-09-23. The audited assets are
   backed up locally at `/private/tmp/msbuild-public-audit/release`; they are no
   longer offered as downloads. No branch deletion or history rewrite was performed.
3. Review the unavailable historical workflow logs and commit identity/privacy
   expectations. GitHub explicitly makes Actions history and logs public on a
   visibility change; review or remove unwanted runs before launch.
   See [GitHub's visibility guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility).
4. At launch, configure private vulnerability reporting and verify the reporting
   path in SECURITY.md. GitHub documents this feature for public repositories;
   its API returned 404 while this repository was private.
   See [private reporting setup](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).
5. Configure main-branch protection and available secret-scanning/push-protection
   controls, and verify them after visibility changes. Protection/ruleset reads
   currently return HTTP 403 with a plan/visibility requirement. This audit does
   not claim they are enabled. Preserve manual CI unless its policy is deliberately changed.
6. Set the repository description, for example:
   `Explicit Bazel rules for .NET projects, retaining MSBuild and SDK behavior.`
   Suggested topics: `bazel`, `dotnet`, `msbuild`, `remote-cache`.

The owner subsequently authorized public repository visibility. The original
audit above and in the JSON records the earlier private snapshot; it is not a
claim that the remaining launch settings have been enabled. The release deletion
and issue cleanup were separate owner-requested operations.

## Repeat the source-history scan

Use the verified Gitleaks version above and a fresh destination:

```sh
git clone --mirror https://github.com/keegan-caruso/msbuild-bazel.git /tmp/msbuild-public-mirror.git
gitleaks git /tmp/msbuild-public-mirror.git --log-opts=--all \
  --redact --report-format=json --report-path=/tmp/msbuild-history-findings.json
gitleaks dir /path/to/prepared-checkout --redact \
  --report-format=json --report-path=/tmp/msbuild-worktree-findings.json
```

These commands return nonzero for the documented false positives. Review each
finding's actual source context; do not treat an alert count or a matching length
alone as evidence that a value is harmless. Release/Actions archives and GitHub
issue/comment data require separate acquisition and archive-aware scans.
