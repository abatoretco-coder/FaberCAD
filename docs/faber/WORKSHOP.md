# Workshop: stock, hardware and PLA

Open **Workshop / Atelier** from Insert or command search. The tabs group wood
stock, PLA templates, material assignment, printer checks and the existing
standard hardware selector. All design actions are also engine/MCP commands.

## Catalogue and materials

`workshop.library {}` lists five generic stock formats (shelf, sheet, back,
batten, worktop), ten wood/panel material presets, three original PLA templates,
the existing standard-parts library and the A1 profile. These are nominal design
templates, not supplier stock, manufacturer CAD or procurement references.

`wood.board` accepts `name`, `material` (catalogue id), `length_mm`, `width_mm`,
`thickness_mm`, and `grain` (`length` or `width`). It creates an ordinary editable
component and material, and stores local stock dimensions and grain/face axis
in component metadata for BOM export. These are original nominal blank
dimensions, not an automatically regenerated cutting list after arbitrary cuts
or feature edits. Measure actual stock before joinery.

Pine, spruce, oak, beech, walnut, birch/poplar plywood, MDF, particleboard and OSB
have nominal density estimates and visual colours. Those estimates do not
constitute a product-specific strength card. `workshop.material` installs and
assigns a preset to named bodies. Existing material names with a conflicting
density are refused; user material properties are not silently overwritten.
Viewport body picks are resolved through their assembly occurrence to the
underlying body definition. Copies of the same component share its physical
material. Invalid picks are rejected before mutation; assigning material is one
undo step.

Wood movement and panel grade require product-specific information:
[USDA Wood Handbook](https://research.fs.usda.gov/treesearch/62260).

## PLA workflow

`print.part` creates a mounting plate with two holes, a bored spacer or an angle
bracket, from editable solid features. It assigns nominal PLA and records the
procedural origin. Creation returns a geometric `print_preflight` report, and
the UI warns when the draft exceeds the default A1 envelope. They are templates
for design, not load-rated hardware.

`print.check` requires explicit body names and accepts `printer` (currently
`bambu_a1_04`), `layer_height_mm`, `line_width_mm` and `bed_margin_mm`. It reads
exact body measurements, checks closed positive-volume solids and the current
axis-aligned envelope with bed margins, and suggests fitting axis permutations.
It flags overall dimensions smaller than the selected extrusion width. These
checks do not measure local wall thickness or certify printability.

The machine is the user's A1 with a 0.4 mm nozzle and 256 mm cubical build
volume. The installed official profile gives layer bounds 0.08–0.28 mm. The
default 0.20 mm layer, 0.42 mm line width and 3 mm margin are editable workshop
assumptions, not calibrated tolerances.

Sources: [Bambu A1 technical specifications](https://bambulab.com/en/a1/tech-specs),
[official Bambu Studio profiles](https://github.com/bambulab/BambuStudio/tree/master/resources/profiles/BBL),
[Prusa design guidance](https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135).

The report separates `ready_for_slicer` from `printable` (unknown). Local wall
thickness, supports/bridges, first layer, combined plate layout, tolerances and
strength remain unverified. A favorable preflight still requires slicing.
Changes to selection, model revision or settings invalidate the UI report.

The Bambu Studio button reuses `file.send_to_slicer` and its background startup
handling, exporting geometric 3MF in mm. Slicer discovery includes bounded
application folders on D: on Windows. The exported file is not a project with
calibrated machine/filament settings: select the real profile and inspect layers.
Sending to the slicer does not send to the printer or start a print.

On Windows encrypted cache folders that reject rename, handoff writes a fresh
copy without overwriting the previous export. The slicer receives the path only
after the complete file is synced. This fallback does not offer atomic rename
visibility to independent folder watchers.

## Qualification

The engine's workshop tests cover volume/BOM/undo, oversized parts, unknown
materials, conflicting densities and invalid dimensions. Reproduce the richer
fixture with `examples/faber/workshop.json`, using an existing empty output
directory at `target/workshop`. Keep exported source, preflight, slicer profile
and layer results together; physical print verification is a separate stage.

Local qualification on 2026-11-08:

- Three focused workshop engine tests passed against the production library.
- Catalogue/BOM fixture: six components, saved/reopened geometry, STL and 3MF,
  invalid inputs rejected. Real MCP: 13 headless calls and four live desktop calls.
- Real Bambu Studio 02.08.02.61 slice using installed A1 0.4 mm and Generic PLA
  profiles: 30 layers, 0.20–6.00 mm; automated checks on every layer, visual
  review of layers 1, 15 and 30. Both mounting holes remain open.
- Mesh: one closed component, 462 triangles, no self-intersections; dimensions
  60 × 30 × 6 mm. Mesh volume agrees with CAD within 0.3%.
- Pointer/keyboard checks created a 450 × 250 × 18 mm shelf and a PLA mounting
  plate, assigned oak, opened hardware, rejected a 0.5 mm layer and invalidated
  stale preflight results. English/French text and decimal commas are supported.
- Six slicer-cache tests passed, including the Windows encrypted-folder fallback;
  writing into the actual affected cache also passed.
- Full native UI qualification passed on the final app (161 recorded actions), including the real
  Workshop button launching installed Bambu Studio with the completed 3MF path.
  Bambu identifies this as geometry-only input, as expected; slicer settings are
  not embedded. The live MCP checks also passed against this rebuilt application.

Artifacts live under `target/workshop/`: `workshop.sc`, `bom.json`, `results.json`,
`mcp-headless.json`, `mcp-live.json`, `ui-qualification.json`, screenshots, and
`slice-20261108-200323/` containing profiles, G-code, layer report and preview.
The final UI-created design is `workshop-ui-final.sc`.
No physical print was launched or certified. Full repository CI was not run.

The initial qualified development app is `target/workshop/faber-atelier.exe`. On this
machine the optimized UI compiler exhausted memory; the verified development
build uses per-invocation `solidcraft-engine` and `solidcraft-ui-egui` overrides
(`debug=0`, `opt-level=0`)
without changing repository build defaults.

## Follow-up bug review (2026-11-08)

Three reproduced defects were corrected:

- Applying a workshop material to a repeated assembly occurrence failed because
  its scene name was passed as a body-definition name. Picks are now resolved
  and deduplicated before assignment, without partial changes for invalid names.
- Suggested fitting orientations could have Z below the selected layer height.
  Suggestions now obey the same minimum height as the current-orientation check.
- An invalid plate width kept blocking a spacer after that field became hidden.
  Spacer commands and previews now derive the unused width from its diameter,
  preserving the draft width for when the plate form is restored.

The two new engine regressions failed before the fixes; all five workshop tests
passed afterward. The real UI spacer regression failed before and passed after
(57 actions, including creation, measured volume and undo). The normal native UI
path also passed on the reviewed executable (155 actions).
The CLI was rebuilt with the same fixes. Its real MCP qualification passed in
both modes: 13 headless calls and four calls connected to the reviewed desktop.
Repository list, UI container, dependency-layer and mesh-decision checks passed;
full repository CI was not run.

Reviewed app: `target/workshop/faber-atelier-reviewed.exe`; saved example:
`target/workshop/workshop-reviewed.sc`; UI regression evidence:
`target/workshop/ui-review-qualification.json`.

## CI and publication

Owner policy changed on 2026-11-09 after the inherited full native test build
exhausted local memory. That build was stopped; it did not validate all tests
and did not result in publication.

Routine validation is now `python scripts/faber_ci.py`: bounded changed-source
checks only (180 seconds / 1 GiB). Native product validation is reported separately.
The earlier workshop results above describe their individual reviewed artifacts;
source-check success does not certify them against subsequent edits.
See [CI policy](CI.md) for exact checks, archived suites and optional artifact smoke.
