# Furniture recipe catalogue

`catalogue/furniture.json` adds **126 original generic design templates**:

| Group | Entries | Contents |
| --- | ---: | --- |
| Stock boards and panels | 36 | Pine, spruce, oak, beech, walnut, birch/poplar plywood, MDF, particleboard and OSB; shelves, battens, worktops and sheets |
| Metric fixings | 56 | Socket/button-head screws and hex bolts in M4/M5/M6/M8, lengths 16/20/30/40 mm; matching nut and washer sizes |
| Other furniture hardware | 34 | Wooden dowels, wood-screw allowances, shelf pins, angle brackets, butt hinges, drawer slides and foot pads |

These are catalogue IDs for design, **not manufacturer part numbers or stock
availability claims**. All dimensions are mm. There is no third-party CAD,
supplier drilling pattern, procurement snapshot or product strength rating.
Board thickness, grade, finish and solid-wood movement need checking against
actual stock. Screws and other proxies do not qualify a joint for manufacture.

## Use now, without rebuilding FABER

The catalogue is external data and command recipes. The existing compiled
Workshop selector keeps its original presets; it does not dynamically load
this file. Codex can read the catalogue, choose an ID and send the resulting
commands through the existing MCP `batch` tool. No embedded AI or new MCP
server is required. No Rust code, dependencies or native build were changed.

From the FABER repository:

```powershell
python scripts/faber_catalog.py list --category board
python scripts/faber_catalog.py list --category hardware --search M6
python scripts/faber_catalog.py show birch_plywood-2440x1220x18
python scripts/faber_catalog.py recipe birch_plywood-2440x1220x18 --name "Cabinet side"
python scripts/faber_catalog.py recipe socket_head_cap_screw-m4x20 --name "Screw 1"
```

The helper only prints JSON. It never launches CAD, writes files, downloads
anything or compiles. `recipe` returns a `commands` array accepted by the CLI
script format and MCP `batch`. An unknown ID returns an error, with no recipe.
Search accepts English names, French labels and exact IDs; no fuzzy product
selection or automatic reference invention occurs.

By default a recipe inserts at the origin in the current design, with a unique
name chosen by the caller. It activates the root component and leaves it active.
It contains no file/open/reset/export command. `--fresh` explicitly adds
`file.new`; use it only for a disposable document. For an existing document,
review the recipe and use MCP batch with its usual error handling. Several
commands contribute to a recipe; this helper does not promise one undo step.

To prepare a standalone sample script, without launching CAD:

```powershell
New-Item -ItemType Directory -Force target/catalogue-demo | Out-Null
python scripts/faber_catalog.py recipe wood-dowel-8x30 --fresh > target/catalogue-demo/dowel.json
```

The JSON can be supplied to the existing CLI's `run` command with `--save` for
a native `.sc` file, inside the repository's resource guard. The bounded
explicit smoke below is the native qualification entry.

## Geometry, editing and BOM

Boards reuse `wood.board` and the existing wood materials/colours and grain
metadata. Metric fixings reuse `parts.insert`; their standard dimensions and
cosmetic threads come from FABER's existing implementation. These entries are
`procedural_standard`, with no claim of manufacturer geometry.

Other hardware uses editable solid boxes/cylinders and nominal material mass
estimates. It is `envelope_proxy`: wood screws have no thread/socket/tip profile;
brackets and hinges have no mounting holes; dowels have no grooves; drawer
slides have no bearings or supplier mounting geometry. Not for manufacturing.
Foot-pad polymer density is a design estimate, not a specified product material.

Hinges and slides create two components with an explicit revolute/slider joint,
one grounded component and designer-selected travel. Hinge length follows Z and
slide length follows X. Neither their travel nor simplified geometry is a
physical hardware rating. They are not attached to any furniture automatically.
All samples start at the origin and may overlap when combined before placement.

Dimensions remain editable through the native features. Modify a recipe's board
parameters before insertion, or edit the resulting features in FABER. Stock
metadata is nominal; arbitrary later feature edits do not regenerate a cutting
list automatically. Standard parts retain `parts.resize` support.

Every created component carries the catalogue ID, units, geometry source/kind,
limitations and a deterministic `recipe_sha256` over its entry. This is a recipe
hash, not a STEP or native-solid hash. Existing stock metadata is preserved.
`assembly.bom` uses the resulting actual component instances; the 126 catalogue
entries are not automatically inserted into a design or counted as procurement.

## Validation and limits

Six lightweight tests cover every emitted recipe, stock/material compatibility,
existing standard-part parameters, provenance, hinge/slide relationships,
explicit reset opt-in and invalid/unknown references. They never run CAD.

`python examples/faber/check-furniture-catalog.py` is an **explicit**, optional
native smoke using only `target/debug/solidcraft-cli.exe`. It creates a dedicated
sample under `target/furniture-catalogue`, selects 11 entries (13 components),
drives both joints, saves SC and checks closed positive-volume solids and BOM.
The guard is 30 seconds, one CPU, 256 MiB aggregate commit and a 192-MiB sampled
working-set threshold, with the existing 4-GiB physical/2-GiB commit headroom
requirements. No installation/build fallback or automatic retry exists.

On 2026-11-11 its preflight refused startup because available physical memory
was below 4 GiB. No native geometry or MCP execution is qualified by that
attempt. The catalogue's native sample therefore remains unverified; source
checks and existing engine-command history are separate evidence.
