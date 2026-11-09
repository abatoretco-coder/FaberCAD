# Development mode and optional CAD importers

FABER's secondary open-format decoders are now opt-in. The existing executable
has not been rebuilt; this document describes the source configuration and
offline dependency checks, not a qualified new desktop binary.

## Safe planning without compilation

From the FABER repository:

```powershell
python scripts/faber_dev.py
python scripts/faber_dev.py --target cli
python scripts/faber_dev.py --foreign-imports
```

These commands only print a JSON plan. They never launch Cargo, rustc, a native
test, a desktop or a network operation. There is no build/execute switch.
The plan includes an absolute manifest path and `working_directory`, so invoking
the script from another folder still describes this checkout rather than a
different project's relative manifest.
`proposed_build_argv` describes a possible later, package-scoped, offline/locked
build; it is not executed and does not authorize one. Native builds still need
separate owner authorization and an enforced time/memory budget.

The development selection disables default features and explicitly keeps
`profile`. It excludes `raytrace-cpu`, `bundled-render-library`, the legacy
embedded assistant and, unless requested in the plan, `foreign-cad-import`.
The GPU viewport dependency remains unchanged. Profiling stays enabled because
the existing evaluation/cache instrumentation relies on it.

## Source configuration

| Selection | Secondary decoders | CPU raytracing | Profiler |
| --- | --- | --- | --- |
| Desktop defaults | Off | On, existing default | On |
| CLI defaults | Off | On, existing default | On |
| Development plan (desktop or CLI) | Off | Off | On |
| Development plan with `--foreign-imports` | On | Off | On |

`foreign-cad-import` forwards from desktop, CLI or web to engine, then IO. Only IO
owns the optional `cadmpeg-core`, `cadmpeg-ir` and `cadmpeg-registry` dependencies.
This enables the pure-Rust FCStd/Rhino decoders; it does not install or launch an
external CAD application and is not a fallback to the retired runtime.

Normal native `.sc`, STEP/IGES and mesh IO remain outside this feature. File
recognition remains independent of decoder availability, so a disabled `.FCStd`
or `.3dm` request reaches an explicit unavailable-import error instead of being
misread as STEP. Import pickers, their extension lists and `import_for_path`
filter those formats out, even if a host passes its old `native=true` flag.
Canonical format metadata (`for_path`/`find`) still recognizes their identities.
Both browser picker paths share one capability-aware extension list. Engine
open/insert requests for disabled formats refuse before reading file bytes.

The normal desktop/CLI defaults intentionally retain the previous rendering
selection; the plan provides the lean feature selection without silently changing
normal render behavior. STEP, document state, undo, GPU and MCP implementations
were not replaced or split into another engine.

## Verification on 2026-11-09

Fresh `cargo tree` inspection used the installed Cargo directly, `--offline`,
`--locked`, Windows target selection and normal dependency edges only. It ran
under a 55-second / 512-MiB guard, without compilation or downloads.
`Cargo.lock` was unchanged. Receipts: `target/development-mode/graphs.json`,
per-selection text trees and `graph-budget.json`.

| Graph | Unique normal packages | cadmpeg packages | Render feature |
| --- | ---: | ---: | --- |
| Desktop defaults | 278 | 0 | CPU raytracing enabled |
| Desktop development | 278 | 0 | CPU raytracing absent |
| Desktop with optional importers | 302 | 7 | CPU raytracing enabled |
| CLI development | 163 | 0 | CPU raytracing absent |

This demonstrates a 24-package reduction for the default desktop versus its
secondary-import-enabled selection. Disabling CPU rendering excludes source
modules even though it does not reduce the desktop package count further.
These are resolved graph measurements, not build-time, peak-RAM or binary-size
measurements. Other dependency kinds are outside this count.

Lightweight CI passes 30 Python tooling tests, manifest/JSON/source checks and
changed Rust formatting checks. It does not compile Rust. Tests were added in
the existing IO/engine areas for disabled import refusal, unchanged document
state and capability-aware format lists; enabled decoder fixtures remain gated
with the feature. **Those native tests have not run.**

The source-review follow-up corrected the browser File System Access picker's
remaining hardcoded extensions, caller-directory-dependent proposed manifest
paths, and unnecessary file reads before disabled-import refusal. The plan-path
regression was reproduced by a failing Python test and passes after correction.
Browser picker and early-refusal Rust regressions were added but are unexecuted;
neither a browser nor a native product was launched for this review.

Future qualification must check both feature states, synthetic native/STEP
save/reopen and linked reloads, disabled-format errors with undo/state preserved,
GPU viewport/picking and unavailable CPU-render behavior. Use repository-local
synthetic fixtures, never furniture projects. A feature/profile change can cause
an expensive first build; no performance target or native readiness is claimed.
