# Security

This project is experimental; fixes target main, with no guaranteed response time.

Report vulnerabilities privately through GitHub's **Report a vulnerability** option
in the Security tab. If unavailable, ask for a private channel in an issue without
disclosing exploit details. Include revision, platform/tool versions, reproduction
and impact. Review logs/binlogs for credentials and private source before sharing.

Build trusted projects: MSBuild targets, analyzers, generators and tasks execute
code. Sandboxing is not a guarantee that hostile projects are safe to build.
Trust your caches/executors; inputs, outputs and diagnostics may contain source or
sensitive data. See [isolation limits](docs/support.md).
