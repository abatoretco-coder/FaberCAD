# Lightweight FABER CI

Owner decision, 2026-11-09: automatic CI checks changed sources, not the inherited
SolidCraft workspace. The 19 upstream workflows are archived outside the active
Actions directory. There are no native builds, browser tests, nightly matrices,
releases, tool installations or artifact uploads in automatic CI.

## Local Windows

Run `python scripts/faber_ci.py` with Python 3.11+ and preinstalled Git/rustfmt.
The Python entry point avoids compiling xtask. A Windows Job Object limits the
entire validation subprocess tree to **1024 MiB committed memory and 180 seconds**.
Timeouts and completion close the Job and stop remaining owned descendants.
The small controller stays outside the Job. No unrelated applications are stopped.
Missing resource protection is a failure; there is no unbounded fallback.

Checks cover tracked modifications and untracked files: Git whitespace, changed
Rust files with `rustfmt --check` and `skip_children=true`, JSON/TOML/Python syntax,
pending locale structure, workflow policy and the small `test_faber_*.py` tooling
regressions. Each subprocess has a short timeout. At most 256 changed paths and
2 MiB per source file are accepted; larger changes fail rather than widening scope.
No Rust type-checking, Clippy or product regression tests are implied by success.

`target/faber-ci/report.json` records `source_checks_only`,
`native_tests: not_executed`, and whether native validation remains necessary.
Previous success is cleared before each run. Failure/timeout never counts as green.
`python scripts/faber_ci.py plan` lists the bounded scope without running checks.

## GitHub and local Linux

One Ubuntu 24.04 job runs on main pushes and pull requests (also explicit dispatch).
The whole job has a **5-minute** timeout and superseded runs are cancelled.
Its validation service has a kernel cgroup limit of **1 GiB RAM, zero swap, one
CPU, 64 tasks and 180 seconds**, with process-tree termination on failure.
Checkout and the small report step are outside that memory cap, inside the job
timeout. Permissions are read-only and checkout does not persist credentials.

Only paths differing from the exact PR/push base are checked. If shallow checkout
lacks that base, validation fetches that single commit under its resource budget.
A missing/invalid base fails; it never silently checks only the latest commit.
The workflow is JSON-formatted YAML so Python can validate it without dependencies.
It uses the runner's installed tools and does not install missing ones.

Linux callers must first enter a real constrained cgroup. The active workflow's
`systemd-run` service command is the executable example for local Linux too:
replace GitHub variables with local uid/gid, workspace and unit name, and omit
`--base` to check the working tree. The guard reads actual cgroup membership and
ancestor limits; an environment variable or address-space limit is insufficient.
Unsupported platforms or missing cgroup protection fail before checks start.

## Optional product validation

`python scripts/faber_ci.py smoke --cli PATH_TO_EXISTING_CLI` runs the workshop
MCP probe under the same limits, without building. It hashes the binary and labels
the result **existing artifact only**, `current_source_verified: false`.
It cannot certify edits made after that binary was built.

Native compilation or larger product suites need a new explicit owner request
and a suitable resource budget. `cargo xtask ci` refuses to run; the old full-CI
orchestrator has been removed. Cargo may compile xtask before its handler, so
always use the Python entry point for routine validation.
Source-check success alone does not authorize publication or prove product health.

## Validation of this change

Only the small CI tooling tests and bounded source checks are run for this change.
Windows resource enforcement is exercised with short, low-memory child probes;
Linux cgroup layouts are covered by fixtures. The GitHub service still needs its
first real runner execution; no remote CI is dispatched by this local change.
