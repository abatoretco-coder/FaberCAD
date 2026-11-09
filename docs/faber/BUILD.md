# Bounded native build: current Windows blocker

Automatic CI remains `python scripts/faber_ci.py`, with its existing hard
1 GiB committed-memory / 180-second validation-tree budget. Native application
compilation is not part of that workflow.

The optional-import boundary and plan-only development selection are now prepared
in source. See [DEVELOPMENT-MODE.md](DEVELOPMENT-MODE.md) for fresh offline graph
measurements and the native checks still pending. This does not rebuild or qualify
the cached desktop executable.

## Diagnosis on 2026-11-09

Rust 1.99.1 maps dependency archives copy-on-write on Windows. Windows reserves
commit for the entire mapped file, even when physical working-set usage is much
smaller. This behavior is present in the [versioned compiler source](https://github.com/rust-lang/rust/blob/1.99.1/compiler/rustc_data_structures/src/memmap.rs)
and tracked in [Rust issue 164655](https://github.com/rust-lang/rust/issues/164655).

The exact cached development graph contains 129 `.rlib` archives totaling about
3,846 MiB, versus about 424 MiB of matching standalone metadata. The engine's
embedded metadata and adjacent `.rmeta` match byte-for-byte by SHA-256. A stale
engine or a different compiler version does not explain the observed failure.

A bounded minimal import typechecks under 1 GiB. A minimal executable using
`Session::default()` fails while mapping a dependency, with Windows error 1455
and Rust E0786. The earlier E0463 error was not a reliable missing-crate diagnosis.
The already-built CI-profile graph is smaller but still about 1,409 MiB. Lowering
build parallelism does not eliminate these archive mapping reservations.

Evidence remains under `target/workshop/build-diagnosis/`. No compiler upgrade,
pagefile change, elevated privileges, global build settings or CI limit change
was made.

## Current owner decision

The owner rejected the proposed 6 GiB commit exception and confirmed that FABER
will continue on SolidCraft. The unapproved runner and its tests were retired to
an ignored local archive under `target/workshop/retired-native-proposal-*`; they
are no longer active project commands. Do not revive them or increase limits.
No FreeCAD migration is planned. The 1 GiB source-validation guard is unchanged.

## First production reduction

Desktop model-provider HTTP and keychain adapters are now compile-gated by
`legacy-embedded-assistant`, which is not a default feature. `keyring` is optional.
The normal application supplies neither model HTTP nor model credential access.
Updates and the shared EasyPrint transport remain independent of this adapter.
The legacy chat UI and automatic client-registration modules are now excluded by
`cfg` from normal production builds. Saved agent preferences use a small data-only
module; they do not load providers, processes or credentials. Shared CLI lookup
and ordinary MCP command dispatch live outside the chat implementation.

Offline, locked Windows dependency graphs were inspected without compiling:

| Graph | Unique normal packages |
|---|---:|
| FABER defaults | 302 |
| Legacy credential adapter enabled | 303 |
| Workshop candidate: no defaults, `profile` retained | 302 |

The first change removes `keyring` from the default graph. It is a bounded first
step, not evidence that the whole app now builds below 1 GiB or that compilation
is faster. Graph receipts are `production-graphs.json` in the diagnosis folder.

## Measured targets for further reduction

- The optional bundled render pack is 216 unique files, only about 10.2 MiB.
  Removing it alone cannot solve the multi-GiB archive-mapping problem.
- CPU raytracing contains roughly 11,000 non-test source lines. Its feature can
  be omitted while retaining the normal GPU viewport, camera and picking.
- Disabling profiling would invalidate profiler-dependent document/kernel/io
  caches. Keep the `profile` feature while evaluating any workshop build.
- The legacy chat UI spans about 22,000 lines including tests. Its module tree
  is now gated out of normal builds, together with its per-document conversation
  state, UI drawing, startup hooks and automatic AI-client registration.
  Data-only preferences and legacy panel identifiers remain for compatibility.
- Foreign-format import uses large `cadmpeg` archives. Assess an optional import
  boundary while preserving STEP, native designs and the required user workflows.

Changing feature sets can create cold cache misses. A smaller graph does not
prove a cheap first build; do not launch one merely to find out under the current
owner restrictions. Keep native UI/registry qualification marked pending.

## Keep SolidCraft, reduce the iteration surface

Keep its geometry engine, native viewport, document and existing MCP as the
authoritative application. Catalogue templates that only compose existing
commands can use JSON recipes and the existing MCP batch path without rebuilding
the core. The reference recipe already demonstrates this limited path.

Do not invent an already available plugin runtime: the current plugin document
is an RFC, not an implemented execution/native-panel system. Do not replace the
MCP with a second transparent proxy merely to avoid a build. New native panels
still need native qualification. A future external workshop planner must solve
local geometry access, revision preconditions and undo before promising the
same guarantees as an atomic in-engine operation.

The legacy assistant UI is excluded at compile time while persisted preferences
and external MCP are retained. Next assess the foreign-import and optional-render
boundaries. Measure a representative
native rebuild's actual time and resource peak before declaring the development
mode lightweight. Passing source checks or dropping one dependency is not that
measurement.

## Assistant UI removal: validation and limits

- Two exact-source data tests passed for serialized legacy configurations, modes
  and original defaults. They compile independently of the UI and CAD engine.
- Five exact-source CLI-link tests passed, including an isolated child-process
  check of the explicit CLI override and deterministic PATH priority/deduplication.
  Their tiny harness adapts only the engine environment reader to std::env.
- Normal `agent_chat` and `ai_connect` module declarations have explicit compile
  gates. Lightweight source policy guards the default-off feature and data-only
  preference boundary. External cursor, token-authenticated control, async jobs,
  screenshots and ordinary CAD command dispatch remain separate.
- Full production UI metadata and dependency-only frontend checks both reached
  the enforced 1 GiB budget. They did not validate the whole UI. Their failure
  receipts are under `target/workshop/ui-source-qualification/`; no resource
  ceiling was increased and no executable was rebuilt.
- `cfg(test)` intentionally retains upstream assistant tests for compatibility.
  A whole UI test-crate build is still large and must not be used for routine
  CAD regression checks. This is not part of automatic CI.
- The currently running cached desktop predates these source changes. No visual
  or live-MCP result on that binary certifies the post-removal executable.
