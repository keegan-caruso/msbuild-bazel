# Security

This is an experimental build integration. There is no supported stable release
line or promised security-response SLA; fixes target the current main branch.

## Reporting

Do not put credentials, exploit details or private source in a public issue.
Use GitHub's **Report a vulnerability** option in this repository's Security tab
when private vulnerability reporting is available. If that option is unavailable,
open an issue asking the maintainer to establish a private reporting channel,
without disclosing the vulnerability itself.

Include the affected revision, platform and tool versions, a minimal reproduction,
impact and any suggested mitigation. Review logs and binlogs before sharing them.

## Trust boundary

Build only projects and MSBuild targets you trust. Targets, analyzers, generators
and task tools execute code. The Linux bubblewrap and macOS sandbox integrations
limit action filesystem access; they are not a claim that arbitrary hostile
repositories are safe to build on your workstation.

Remote caches and executors must be trusted and configured for your organization.
Action inputs, outputs and diagnostics can contain source code or sensitive data.
The Buildbarn fixture in this repository is for an isolated qualification network;
it deliberately has no authentication and is not a production deployment recipe.
See [worker isolation](docs/explicit-linux-workers.md) and
[remote execution](docs/remote-execution.md) for the measured boundaries.
