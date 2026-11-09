# Workshop implementation

User outcome: catalogue CAD, nominal wood stock and wood materials, and PLA
design checks tied to the user's Bambu A1 0.4 mm profile, through UI and MCP.

Reuse: parts.library/parts.insert, material.create/assign, ordinary parametric
solids, component metadata/BOM, exact inspect.measure, print faces, STL/3MF and
file.send_to_slicer. No embedded AI, new persistence format or external CAD.

Implementation order:
1. Add workshop catalogue, wood board and printable-template commands with
   typed contracts; keep stock and material assumptions explicit.
2. Add printer-profile and model preflight commands. Report measured geometry,
   build-volume fit, orientation candidates, blocking issues and unmeasured
   wall/support/strength risks. Never equate envelope fit with printable.
3. Add an accessible Workshop dialog reusing the existing UI kit and slicer
   handoff, with French strings and deterministic external handles.
4. Verify positive/negative/hostile inputs, undo/reopen/BOM, standard hardware,
   export, actual local A1 slicing and native desktop/MCP paths.

Design review: a second hardware catalogue or custom slicer pipeline would
duplicate existing functionality; reuse them. Bounding boxes cannot determine
minimum wall thickness or guarantee supports: label those checks unknown and
require slicing. Nominal wood density is an estimate for mass, never a material
strength card. Validate before mutation and reject stale material-name conflicts.
Catalogue templates are procedural, not supplier-certified CAD.

Acceptance: users can insert adjustable stock boards, choose wood/PLA finishes,
insert known hardware, make a printable template, see printer-dependent reasons
for blockers/unknowns, and hand the selected part to the installed slicer. An
oversize or nonclosed part cannot receive a successful preflight status.
