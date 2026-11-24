# Security

Experimental project: fixes target `main` with no guaranteed response time.

Report vulnerabilities privately via GitHub's **Report a vulnerability** in the Security tab (or request a private channel in an issue without exploit details). Include revision, platform/tool versions, reproduction, and impact. Scrub credentials and private source from logs/binlogs before sharing.

Build only trusted projects: MSBuild targets, analyzers, generators, and tasks execute code; sandboxing does not make hostile projects safe. Trust your caches/executors—inputs, outputs, and diagnostics may contain source or sensitive data. See [isolation limits](docs/support.md).
