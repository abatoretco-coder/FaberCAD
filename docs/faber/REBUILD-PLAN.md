# Targeted desktop reconstruction plan — no execution

Prepared on 2026-11-09 against source baseline `45adbae03`. This plan does not
authorize or start a compilation. It does not modify compiler versions, profiles,
CI limits, system settings or furniture projects. The existing desktop remains
available and must not be overwritten or launched by the reconstruction attempt.

## Scope

One desktop binary: package/bin `solidcraft`, using the current dev profile and
existing `target/` cache. Disable default features and explicitly retain only
`profile`. No CPU raytracer, bundled render assets, secondary importers, embedded
assistant, CLI/web/workspace builds, tests, release packaging or application run.
Keep `.sc`, STEP, GPU viewport and MCP implementations.

`python scripts/faber_dev.py` prints the proposed Cargo arguments and limits as
JSON. It does not invoke Cargo. The proposal is offline/locked, names an absolute
desktop manifest, and includes `--jobs 1`; it must never be executed directly
without the guard described below. No compiler/toolchain/package downloads.

## Limits for one future feasibility attempt

| Limit | Value | Enforcement required |
| --- | --- | --- |
| Attempts | 1 | No automatic retry or fallback |
| Wall time | 120 seconds total | One deadline covering guard setup, Cargo and descendants |
| Aggregate committed memory | 1,024 MiB | Windows Job Object, before releasing the bootstrap |
| Physical working-set abort threshold | 768 MiB | Poll the attempt's process tree every 100 ms; abort on crossing |
| CPU | 1 logical processor | Inherited Job affinity, plus Cargo `--jobs 1` |
| Available physical memory | At least 4,096 MiB | Preflight and watchdog; refuse/abort below this |
| Available system commit | At least 2,048 MiB | Preflight and watchdog; refuse/abort below this |

The hard Windows memory limit concerns **aggregate committed memory**, not every
kind of physical resident page. The working-set threshold is sampled and can
briefly be crossed between measurements; summing process working sets also counts
shared pages more than once, conservatively. Neither it nor a Job commit limit
is an absolute aggregate physical-RAM guarantee. If the owner requires that
stronger guarantee, do not run this Windows plan.

If any limit cannot be installed or observed, fail closed before starting Cargo.
No elevation, pagefile adjustment, new compiler, larger budget, second attempt or
remote build is a fallback. The prior rejected 6-GiB proposal remains retired.

## Cache expectations

Read-only inspection of `target/debug/.fingerprint` found cached desktop features
with CPU rendering and bundled assets, but no desktop fingerprint matching the
new profile-only selection. The engine cache also lacks that exact selection;
the IO cache predates the new optional-decoder configuration. Feature matches
alone would not prove a cache fresh against the changed sources.

| Area | Expectation before the attempt |
| --- | --- |
| IO, engine, UI, desktop | Source/configuration changed; expect reconstruction |
| Render, document | Matching-looking artifacts exist; reuse is not proven |
| Geometry, sketch, kernel and external dependencies | Reuse only if Cargo considers their exact fingerprints fresh |
| Secondary decoders and CPU raytracer | Must not be enabled by the selected graph |

The normal graph has 278 packages, not just the desktop's own crate. An argument
selecting one binary does not prevent Cargo rebuilding dependencies. Before any
compiler invocation, an execution guard must enforce a compile allowlist for
the intended local areas: IO, render, doc, engine, UI and desktop (including their
own build scripts). If it needs to rebuild other packages, especially solidcore,
wgpu or an external build script, stop before that compilation begins. Cargo log
monitoring after a process starts is insufficient for this promise.

No cache deletion, copy of the entire cache, new target directory or profile
change is planned. Keep reviewed executables under `target/workshop/` separate
from Cargo's normal desktop output. A successful binary is a candidate, not an
automatic replacement or a qualified release.

## Execution gate — currently not ready

`scripts/ci/resource_budget.py` now provides an opt-in `WindowsWatchdog` alongside
the existing aggregate Job commit ceiling and deadline. It installs and reads
back a one-processor Job affinity before releasing its waiting bootstrap. It
samples every owned process's working set, checks its affinity, and observes
system physical/commit headroom through `GetPerformanceInfo`. Loss of telemetry
refuses startup or stops the owned Job. Closing stops and waits for its process
objects as well as draining membership; unrelated processes are untouched.

The default source-CI launch remains unchanged; these extra Windows guards are
opt-in and do not silently become an unsupported Linux fallback. `--jobs 1`
alone remains insufficient to enforce one CPU.

Twenty-four targeted budget tests passed, including real Windows parent/child
affinity, attempted widening, working-set abort, 128-MiB commit-pressure refusal,
timeout/success descendant cleanup and an unrelated live spectator. Tests also
inject missing telemetry and low-memory readings, before and after startup.
Synthetic probes use smaller 128/192-MiB commit limits, under a 256-MiB outer
test-tree ceiling; they do not allocate the production memory allowance.

The working-set sum counts shared resident pages repeatedly, independently of
Job commit. Each has a separate global ceiling of 1 GiB; the production plan
still uses 768 MiB sampled working set and 1,024 MiB committed memory. A deadline
terminates the payload at expiry; verifying descendant teardown can take up to
five additional seconds. This verification is not permission for payload work
after the deadline.

The [compiler/dependency request policy](REBUILD-POLICY.md) is connected through
the [Windows Cargo adapter](CARGO-GATE.md). Compiler calls, already cached build
scripts and their children are intercepted before user code. Qualification uses
fake tools and installed Cargo on a tiny disposable workspace with a fake
compiler. No Rust compilation or actual FABER dependency build has occurred.
The plan remains `ready_to_execute: false`: real compilation is unauthorized,
and real helper/tool identities and cached-script pins still need qualification.

Before any later owner-authorized compilation:

1. Review and pin the actual compiler, any required linker/resource helpers and
   cached local build scripts. There is no default helper or script permission;
   newly produced script artifacts are not automatically trusted.
2. Retain the qualified process gate and resource ceiling. Unsupported compiler
   arguments, helper processes or architectures must stop the attempt, without
   broadening permissions or starting an unguarded fallback.
3. Record source/lockfile hashes, compiler identity, the exact selected graph,
   environment overrides and the existing desktop artifact hashes. Sanitize
   only the attempt's environment so wrappers, flags or jobs cannot broaden it.
4. Require explicit owner authorization for the single guarded build attempt.

Do not run the proposed Cargo argv merely because this document or JSON exists.
The adapter supplies only an internal guarded worker, with no public build CLI.

## Stop and result handling

On failure, timeout, memory/headroom threshold, missing telemetry or a forbidden
compile request, terminate only the attempt's Job and all its descendants. Write
a receipt containing the reason, elapsed time, committed-memory counter, sampled
working-set maximum, packages started and cleanup outcome. Do not retry, clean
the cache or replace the existing executable. A refused memory allocation may
appear above the cap in the raw accounting counter; do not disguise that value.

On success, record the artifact hash and resource measurements; leave it stopped.
Opening it, checking UI/MCP with a small synthetic fixture and promoting it to
the reviewed executable are subsequent actions. Furniture projects are never
part of this feasibility attempt.

The earlier Windows build failures and the remaining engine size mean success
under these limits is uncertain. This is a bounded feasibility test, not a
promise to obtain a complete desktop within two minutes or below 1 GiB.

Win32 contracts used here: [Job affinity](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information),
[Job process membership](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_process_id_list),
[working-set telemetry](https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-getprocessmemoryinfo)
and [system page/commit counters](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-performance_information).
