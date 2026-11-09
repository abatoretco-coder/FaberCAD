# Cargo process gate — fake compiler qualification

Implemented on Windows x64 in `scripts/ci/cargo_adapter.py` and
`scripts/ci/windows_process_gate.py`, connected to `rebuild_policy.py` and the
existing Windows Job resource guard. There is no public build/execute CLI.
`faber_dev.py` still prints a plan and `ready_to_execute: false`.

## Before each process executes

A disposable guarded worker starts the pinned Cargo executable as a debuggee.
Windows reports creation of Cargo and its descendants before their user code
runs. The worker reads the actual executable image handle, command line,
working directory and only the two Cargo package-identity environment values.
It verifies executable/prefix-file SHA-256 pins and parent roles, then authorizes
the process before resuming it. It does not log environment contents.

Only the exact offline/locked, single-job, profile-only desktop command is
accepted. Compiler requests go through the local package/source policy; a small
explicit read-only compiler probe subset is handled separately. Cargo metadata
labels alone do not establish source identity. Unknown flags and processes stop
the attempt. Compiler/wrapper/target flag environment overrides are removed.

Already cached build scripts are intercepted even without a compiler request.
They need a package-bound artifact SHA-256 pin and unchanged local build-script
source. There are no default script pins or helpers. A trusted script's children
are checked too; a shell, linker or other helper is never authorized by its name.
New script artifacts are not automatically enrolled as trusted artifacts.

On refusal the pending create event is not resumed. The disposable debugger
worker exits and kill-on-debugger-exit plus the enclosing Job terminate the
attempt's descendants. Job limits, one-CPU affinity, deadline, working-set and
system-headroom monitoring remain in force. No other application is attached
or stopped and no global debugger/system setting is changed.

## Qualification, without compilation

Fifteen adapter tests cover allowed local calls, external/source identity
refusal, cached scripts with/without pins, forbidden descendants, changed tools,
read-only probes, environment sanitization, unsupported platforms and refusal
of unauthorized real-tool mode or weakened production headroom. Receipts record
the resource outcome and verified descendant cleanup; they are replaced
atomically, with any old success cleared before the next attempt starts.

Two tests use the already installed Cargo executable directly (no rustup shim)
on a tiny temporary workspace containing only text source fixtures. A fake
`rustc.exe` consists of an existing Python console launcher plus a ZIP payload;
assembling it requires no compiler or installation. The payload answers version
and target queries and writes **text placeholders** as artifacts. It never
parses Rust, links code or starts an artifact. The process gate permits only
that pinned launcher and its pinned Python interpreter delegation.

The positive test exercises Cargo's actual probe and local compile-request
arguments. The negative test adds a forbidden dependency: its fake compiler
process is stopped before its payload executes. Cargo may print `Compiling` as
it schedules a request; this log is not evidence that a compiler ran.

These tests are offline with a private Cargo home, under a 192-MiB aggregate
commit ceiling, one CPU and 10-second deadline per Cargo attempt; other adapter
process tests use 5 seconds. A separate outer qualification uses 256 MiB.
Installed-tool tests skip when their prerequisites are absent; they never
download or install tools. Windows interception tests skip on other platforms.

## Limits and next authorization

This is a conservative execution guard, not a hostile-code security sandbox.
It does not isolate file/network operations inside trusted Cargo, a permitted
compiler, script or proc macro. Entry-point hashes do not freeze every Rust
module, linked library or cache artifact. Source/cache freeze and actual tool,
helper and artifact qualification remain necessary for a real build attempt.

The remote process-parameter reader supports only the tested Windows x64 layout;
missing telemetry, unsupported architectures or unreadable data fail closed.
Future OS/Cargo forms need review rather than automatic permission expansion.
Native FABER sources and executables remain unvalidated by these fake tests.
No furniture projects are part of this qualification.

Actual compilation still requires separate explicit owner authorization and
the existing one-attempt, 120-second / 1-GiB ceiling. Tests introduce no retry,
cache deletion, desktop promotion or automatic build option.

Win32 references: [debugging events before user code](https://learn.microsoft.com/en-us/windows/win32/debug/debugging-events),
[event handling and debugger thread](https://learn.microsoft.com/en-us/windows/win32/api/debugapi/nf-debugapi-waitfordebugevent),
[process parameter layout limitations](https://learn.microsoft.com/en-us/windows/win32/api/winternl/ns-winternl-rtl_user_process_parameters).
Cargo: [compiler-wrapper configuration](https://doc.rust-lang.org/cargo/reference/config.html).
