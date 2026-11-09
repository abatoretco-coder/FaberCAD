# Targeted development-cost audit

Date: 2026-11-09. Scope: the FABER software repository only. No compilation,
Cargo invocation, application launch, dependency installation, CI dispatch or
furniture-project access. No production code or build settings changed.

Follow-up: the separately requested source implementation is documented in
[DEVELOPMENT-MODE.md](DEVELOPMENT-MODE.md). Its optional importer boundary and
plan-only development selection have fresh offline graph checks, but no native
build or product qualification. The findings below describe the audit baseline.

Local measurements and source hashes are in
`target/development-audit/evidence.json`. The repository already had uncommitted
implementation work; this audit does not qualify that work or rebuild its binary.

## Findings

### 1. Native iteration still reaches large shared crates

The dependency direction is desktop -> UI -> engine -> IO/document/kernel.
The CLI also depends directly on the engine, MCP and GPU crates. Using a headless
CLI does not itself remove native compilation costs.

Raw source counts below include tests, comments and conditionally inactive code;
they are source-surface indicators, not compiled-line or timing measurements.

| Source crate | Rust files | Raw lines |
| --- | ---: | ---: |
| ui-egui | 462 | 382,314 |
| engine | 483 | 263,518 |
| doc | 243 | 83,737 |
| kernel | 155 | 69,614 |
| render | 140 | 54,795 |
| io | 34 | 18,874 |

The current debug cache contains individual engine archives around 1,040-1,052
MiB, solidcore archives around 713 MiB and cadmpeg IR archives around 577 MiB.
The entire debug archive cache is 18,311.9 MiB across 546 files, including duplicate
feature/build variants; it is **not** one dependency graph or a RAM requirement.
The CI-profile cache likewise contains variants (315 archives, 2,239.0 MiB).

The earlier exact-graph diagnosis in [BUILD.md](BUILD.md) identified approximately
3,846 MiB of dependency archives and a Windows commit-mapping failure under the
existing budget. Those historical failure measurements were not rerun here.
A small test-name filter still requires compiling its containing engine/UI test
crate; it is not an isolation boundary.

### 2. Secondary CAD importers are mandatory dependencies

`crates/io/Cargo.toml` unconditionally includes `cadmpeg-core`, `cadmpeg-ir` and
`cadmpeg-registry`. The workspace registry enables the FCStd, Rhino and STEP
codecs. Every engine client therefore inherits those dependencies.

The existing seam is `crates/io/src/native_cad.rs`: it converts foreign files to
STEP text. `step_import_feature_named` stores that STEP text, independently of
the foreign decoder. The native `.sc` document, normal STEP reader and meshes
must remain supported. The pure-Rust FCStd decoder is distinct from installing
or launching the retired CAD application; this audit does neither.

**Recommended first source reduction:** make this secondary importer boundary
optional, with its dependencies and tests behind one coherent feature propagated
to the desktop and CLI. Use the existing format-catalog capability filter in
`formats.rs`; the desktop currently calls `open_extensions(true)`. An omitted
decoder must disappear from pickers and return an explicit unsupported-format
error through CLI/MCP. Never route an omitted codec into the normal STEP parser.

Acceptance, before calling the change usable: normal graph excludes cadmpeg;
native/STEP fixtures still open, edit, undo, save and reopen; omitted formats fail
cleanly; full-import mode retains its decoder tests. Embedded historical import
features and linked-file reloads need explicit checks, not an assumption that
all existing `.sc` documents are independent of every original source format.

### 3. Optional rendering is still enabled by default

Desktop defaults are `raytrace-cpu`, `bundled-render-library`, `profile`; CLI
defaults are `raytrace-cpu`, `profile`. The existing CPU-render feature gates a
24,758-line raw source subtree, including tests. It is separate from the GPU
viewport needed for navigation, picking and interactive CAD.

A development mode retaining `profile` and omitting optional CPU rendering is a
candidate, not a verified lightweight binary. Render commands must report their
unavailability correctly, and GPU snapshots/viewport must remain functional.
The optional bundled render pack was previously measured at only about 10.2 MiB;
removing assets alone will not solve the native build problem.

Historical graph receipts count 302 normal packages for both the default desktop
and the no-defaults/profile candidate, versus 303 with the legacy assistant.
These are cached receipts, not a fresh resolution. Package count alone misses
the benefit of excluding source modules; it cannot predict time or peak memory.

### 4. Assistant removal is already in progress, not the next major saving

Production `agent_chat` and `ai_connect` modules are already gated behind
`legacy-embedded-assistant`; keyring is optional. External MCP and data-only
preferences remain separate. Do not redo this work or remove MCP to shrink FABER.

`cfg(test)` still includes the legacy assistant, so building the entire UI test
crate brings it back. Some image-decoding features also remain unconditional,
but clipboard and other UI uses must be traced before removing them. This is a
secondary cleanup, not the strongest demonstrated next reduction.

### 5. There is already one useful loop without rebuilding

JSON recipes and MCP batches can compose the existing executable's commands to
exercise dimensions, catalogue templates, materials, assemblies and geometric
checks. Existing examples include `examples/faber/design-reference.json` and
`check-workshop-mcp.py`. Use disposable synthetic fixtures under this repository's
`target/`; never use a user's furniture project as a development scratch file.

This validates the existing executable and those recipes. It does not register
new Rust commands, update native panels or prove that unbuilt handlers work.
The plugin system is explicitly a draft in `docs/rfcs/0002-plugins.md`; no plugin
runs. Do not promise native hot reload or invent a parallel CAD engine/proxy.

## Recommended sequence

1. Keep routine development on bounded source checks and small synthetic MCP
   recipes. Record the exact binary and distinguish source/runtime evidence.
2. Implement the optional foreign-import boundary first, then a scoped desktop
   development feature selection without the optional CPU renderer. Retain the
   profiler, normal CAD kernel, native viewport, STEP, `.sc`, undo and MCP.
3. Isolate genuinely pure workshop calculations/contracts from `Session` only
   where they have a clear domain owner and worthwhile focused tests. Reuse that
   code in production; do not create a second algorithm in a test harness.
4. Avoid bare workspace Cargo commands: there are no `default-members`, and the
   workspace includes all crates, desktop, CLI, web and xtask. Future authorized
   native checks must name a package/target and one consistent feature/profile.
5. After separate owner authorization, measure one representative incremental
   edit and a cold build separately: wall time, aggregate committed-memory peak,
   working set, rebuilt packages and cache footprint. Stop at the agreed limit.
   No successful build under 1 GiB or new duration estimate is claimed here.

Changing features, profiles, compiler version or output directory can invalidate
cached artifacts and cause an expensive first build. Do not run one during this
audit. Do not use `cargo clean`, delete the useful existing caches, raise memory
limits, restore heavy CI or replace SolidCraft to hide this problem.

## What can improve without a build

| Change | Existing-binary iteration | Native rebuild needed |
| --- | --- | --- |
| Recipes/scenarios using existing commands | Yes, on synthetic fixtures | No |
| Documentation and source-only checks | Yes | No |
| New Rust command, domain implementation or native panel | Source review only | Yes, for native qualification |
| Importer feature boundary / development feature selection | Static review only | Yes, with initial cache cost |

The audit is complete. Implementation and any later native build are separate
steps; the owner restriction against compilation remains in force.
