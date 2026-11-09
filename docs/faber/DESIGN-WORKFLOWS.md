# Woodworking and furniture design workflows

This increment extends Workshop using the existing engine, component metadata,
solid features and joints. It adds no AI runtime, dependencies, document-format
change or alternate CAD model. All new engine commands are registered for the
normal CLI/MCP dispatcher and the native Workshop dialog has matching tabs.

## Actual-contact dowel drilling

`wood.joinery` takes exactly two workshop wood bodies and derives their common
face from actual solid geometry. It accepts axis-aligned rectangular boards,
including supported assembly placements, and refuses gaps, overlap, ambiguous
contact, previously machined stock and shared definitions placed several times.

Example parameters:

```json
{
  "bodies": ["Lower", "Upper"],
  "diameter_mm": 6,
  "clearance_mm": 0.2,
  "depths_mm": [8, 8],
  "count": 2
}
```

Hole centers are spaced on the longest axis of the actual shared face. Explicit
world-space `centers_mm` can replace `count`. The command checks that all bores
fit in both boards, remain blind and do not intersect each other. The 1 mm
residual/edge margin is only a geometric guard, not a woodworking design rule.
Clearance is added to the hole diameter, not to its radius.

This creates matching holes, not physical dowels or a rigid assembly constraint.
Select and trial-fit the actual dowels, wood, adhesive and tooling. Drill features
are editable but their positions are captured at creation: after changing stock
dimensions, recheck/recreate the drilling pattern. It is not an associative joint
generator for arbitrary subsequent feature edits.

## Recomputed cutting list

`wood.cut_list {}` measures body definitions in component-local coordinates,
rather than global placement bounding boxes. It uses current BOM quantities and
current material assignment. Scaling a board updates its reported dimensions;
placing the same board twice changes its quantity, not its local dimensions.

Rows include declared grain direction and distinguish a rectangular blank from
the envelope of a machined/profiled part. Grain is declared stock metadata and
must be checked after feature rotations/shears. The report is never marked
`fabrication_ready`: kerf, allowances, tenon extensions, edges, stock defects and
nesting remain separate decisions. The UI invalidates its report after edits.

Only explicitly prepared workshop stock is included. This is not an automatic
stock interpretation of every imported STEP component.

## Furniture hardware

`furniture.library {}` lists an original generic butt-hinge envelope and a generic
drawer-slide envelope. `furniture.insert` accepts `name`, `template`,
`length_mm`, `width_mm`, `thickness_mm`, optional `travel` and
optional `clearance_mm`. It creates one grounded and one movable component with
a real revolute/slider joint and nominal travel limits.

Hinge length follows its Z pin axis; hinge width describes the flat/open span.
Slide length follows X travel. Travel is degrees for a hinge and mm for a slide.
The supplied dimensions, clearances and travel are design assumptions.

Provenance is explicitly `envelope_proxy`, original FABER geometry, mm units,
`generated_from_evidence: false`, no manufacturer reference and no third-party
CAD. These envelopes have no mounting holes, supplier drilling pattern or load
rating. Real manufacturer selection, sourced fitting diagrams and their proper
STEP import remain necessary before final drilling. The generic catalogue does
not close that supplier-library gap.

## PLA and end-to-end checks

The existing `print.part`, `print.check` and Bambu handoff remain the PLA path.
No favorable envelope check certifies supports, minimum local wall thickness,
strength, fit, first layer or a physical print. The existing qualified PLA plate
and A1 slicing evidence remain in [WORKSHOP.md](WORKSHOP.md).

The explicit small qualification entry is
`python examples/faber/workshop-design-tests.py --engine PATH_TO_CACHED_ENGINE_RLIB`.
By default it only typechecks the exact new handlers and their tests over an
explicitly matched cached engine, with an aggregate 1 GiB / 45-second ceiling
and no Cargo fallback. Runtime compilation/linking and test execution require
explicit `--run-tests` and remain bounded to 1 GiB / 170 seconds.
It records source hashes, engine identity and the precise validation scope under
`target/workshop/design-qualification/`. No heavy suite is added to automatic CI.

The cached desktop and MCP executable cannot discover newly registered commands
until rebuilt. Handler qualification does not certify that new UI or dispatcher.
The existing desktop can display compatible generated native `.sc` previews,
because the geometry uses its existing solid features and joints.

## Observed qualification for this increment

- Exact native source typecheck passed for both modules and all 11 test cases.
  This is not a runtime test pass. Linking the cached engine exceeded the 1 GiB
  budget; native runtime attempts were stopped without increasing that ceiling.
- The expanded `examples/faber/design-reference.json` is a separate fixture using
  already available commands, not the newly compiled handlers. A real MCP stdio
  run completed 22 calls: paired blind-bore volumes/materials, dimension change
  and undo, hinge/slide movement, six BOM items, save/reopen and PLA preflight plus
  3MF export. No physical print or new UI/dispatcher qualification is implied.
- Reference documents are local at
  `target/workshop/design-reference/wood-furniture-reference.sc` and
  `pla-reference.sc`; protocol evidence is `mcp-reference.json` beside them.
  Reproduce with `check-workshop-mcp.py --design-reference` under the resource
  guard; it refuses `--connect` to avoid replacing a user's open document.
- The new native Workshop tabs are implemented in source. They are not present
  in the previously built reviewed desktop, which is kept for reference viewing.
