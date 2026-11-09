# Reconstruction request policy — synthetic qualification only

`scripts/ci/rebuild_policy.py` authorizes requests without executing tools. It is
not itself a Cargo adapter, compiler wrapper or OS process sandbox. The separate
[Cargo adapter](CARGO-GATE.md) connects it to Windows process creation. No real
compiler, external build script or furniture project was used to qualify it.

## Authorized units

Only these exact package directories are eligible:

| Package | Directory |
| --- | --- |
| solidcraft-io | crates/io |
| solidcraft-render | crates/render |
| solidcraft-doc | crates/doc |
| solidcraft-engine | crates/engine |
| solidcraft-ui-egui | crates/ui-egui |
| solidcraft | apps/solidcraft |

The policy resolves and hashes each manifest, its library/desktop entry point
and its own build script when present, plus the workspace manifest and lockfile.
It checks actual manifest identity, canonical source path, crate name/type and
working directory together. A crate name alone or caller-supplied package label
does not authorize a source. Version/metadata probes are not implicitly allowed.

Missing files, changed recorded hashes, paths outside the package, extra sources,
response files, tests, unexpected crate types/targets, unknown options or cfg
forms fail closed. Only `profile` and `default` feature cfg values are accepted;
CPU rendering, secondary importers and legacy assistant cfg flags are refused.
Output options must point inside this checkout's `target/debug`, and redirected
emit paths are refused. This cannot replace the reviewed workshop executable.

This is a conservative supported argument subset. A new legitimate Cargo form
must be reviewed and tested; an unknown form is never silently forwarded. It
does not sandbox arbitrary behavior inside trusted Rust source or proc macros,
and entry-point hashing is not a snapshot of every transitive module/artifact.
Concurrent changes still require the future attempt's source-freeze policy.

One refusal latches the policy object into a denied state. Later requests in
that attempt are refused too; there is no reset or automatic retry operation.

## Cached build scripts

Rustc interception alone is insufficient: Cargo can run an already compiled
`build-script-build` program without requesting a new compile. Such execution
requires an independently supplied, package-bound SHA-256 artifact pin. No pins
are accepted from a compile request; there are none by default. The artifact
must live under the debug build cache, and both artifact and recorded local
build-script source must match. External packages remain disallowed even if
their crate name resembles an authorized one.

Tests use inert text files as pinned-artifact stand-ins; they are never executed.
This does not qualify actual cached executable scripts or a mechanism to capture
new artifacts securely after a future authorized compilation.

## Tests and evidence

Eleven focused tests cover local units, own build scripts, external crate-name
spoofing, source/path substitution, output escapes, hidden/unknown arguments,
feature/test requests, hash changes, denial latching and pinned cached scripts.
One source-symlink test is skipped on this Windows host because the required
symlink privilege is unavailable; equivalent path traversal cases still run.

The process-level harness runs fixed, tiny Python programs as fake compilers.
An allowed request writes its invocation marker. The next external-package
request is refused; its marker and that of a later local request are absent.
On Windows the harness is bounded by the existing Job/CPU/RAM guard (192-MiB
inner commit limit, 256-MiB outer qualification tree). On Linux it verifies and
reuses the existing CI cgroup cap, at most 1 GiB; it does not create a nested
192-MiB limit. Missing or oversized cgroup limits refuse launch. No OS memory
limit or workflow budget is increased. Each worker retains its 5-second deadline.
No request can choose a real executable in this harness.

The initial policy qualification ran 53 lightweight tests: 52 passed, one
skipped. Current adapter qualification is recorded in [CARGO-GATE.md](CARGO-GATE.md).

## Execution integration

`cargo_adapter.py` now routes compiler and cached-script process creation through
this policy before execution, pins tool identity, sanitizes wrappers/environment
and retains the CPU/RAM/deadline Job over the entire process tree. A denied child
is never resumed; the attempt stops. Watching Cargo logs is not the gate.

The development plan remains `ready_to_execute: false`. Fake-compiler and cached
script qualification does not authorize real compilation, qualify native FABER
artifacts or provide an adversarial sandbox for trusted source/compiler code.
