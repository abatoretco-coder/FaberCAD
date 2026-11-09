# Headboard as a FABER motion qualification fixture

The headboard is a user-owned integration fixture for FABER, not a furniture
redesign. Its prepared design is currently local at
`target/headboard-comparison/headboard-assembly.sc`; it is not bundled in git.
The fixture restores 28 components and six revolute joints from a FreeCAD STEP
export and independently captured poses.

From the repository root, run:

```powershell
./examples/faber/check-headboard-motion.ps1 -Design path/to/headboard-assembly.sc
```

The reusable scripts exercise the same engine commands exposed by MCP execute
and batch. This run uses the CLI, not an MCP client or the desktop interface.
They check moving parts against the structure and against each other at 41
samples, reject incomplete results, and export a 31-frame animation. A completed
check with collisions demonstrates detection, not furniture clearance.

Observed on 2026-11-08:

- Both checks completed, without truncation: 160 and 28 occurrence pairs.
- Six colliding pairs against the structure and two between moving parts.
- Combined lid/flap opening first overlaps at study step 0.5 (2.5% of travel).
- Animation exported successfully with 31 frames and 813828 bytes.
- Independent analytic reference: two 10 mm cubes, initial gap 10 mm, slide
  15 mm towards each other. A 5 mm slide remains clear. A 15 mm slide sampled
  every millimetre first overlaps at step 11 and shares exactly 500 mm3 at
  step 15. Both expected outcomes pass and are asserted by the runner.

The checks are discrete samples, not a continuous swept-volume proof. Initial
overlaps need independent examination to distinguish intended construction
intersections from faulty placement. No fixture geometry was changed to hide
these detections.

Product defect found during inspection: the Motion Study dialog displayed
"no collisions" for an empty result even when checking was truncated. The
dialog now requires an explicitly clear, nontruncated, empty result. A focused
regression covers complete, partial, inconsistent and missing results.

Validation: the exact production predicate and its exact new regression test
were mechanically extracted and compiled against the existing serde_json
dependency; the regression passes. Rust formatting and diff checks pass. The
existing desktop interaction test passes on the previously built test binary.
The full UI test crate rebuild was stopped after more than 15 minutes; the
modified UI crate and its rendered partial-result state have not been validated
as a whole. No full CI, commit, merge or push was performed in this step.

Remaining qualification after the initial CLI pass was live MCP execution,
interactive desktop inspection and individual joint sweeps to refine blocking
angles. Live desktop/MCP results from the follow-up are recorded below.

## Live desktop and MCP probe

Launch a dedicated app window with the prepared fixture and `--control 27915`.
The following probe reads its local token without logging it:

```powershell
python examples/faber/live_motion_probe.py --mcp
python examples/faber/live_motion_probe.py --ui --output target/headboard-comparison/live-ui.json
```

The MCP probe creates a real stdio client connected to the running desktop,
initializes the protocol, discovers tools and calls `execute`. It asserts
midpoint/closed joint values and the known sampled collision. The UI probe uses
real pointer events on published handles: play, stop, start, slider drag,
collision check and a collision row. It saves native window screenshots for
visual review. Run on a dedicated fixture window: playback changes the pose.

Live inspection exposed repeated egui IDs on track value editors when several
tracks have keys at the same step. Each track now owns an ID scope. Transport
buttons publish `motion:start/back/play/stop/forward/end`; the timeline slider
publishes `motion:slider_start/end` for repeatable external interaction.

Follow-up results on 2026-11-08:

- The corrected desktop app built successfully with `cargo build -j 1 -p
  solidcraft` (15m28s). This supersedes the initial compilation limitation above;
  the full test crate/CI suite was not run.
- Native-window inspection confirmed the duplicate-ID warnings on keyed track
  values before the fix and their absence after track scoping.
- The UI probe completed play, pause, slider drag, collision checking and a
  click on the first collision row, with native screenshots for review.
- The global UI check exposes 21 colliding pairs, including fixed/fixed
  construction intersections. The filtered moving-part checks expose eight;
  these counts have different scopes and must not be conflated.
- A real MCP stdio client bridged to the rebuilt running desktop completed
  initialization, tool discovery, joint inspection, midpoint/closed playback
  and collision checking. It asserted 27.5 degrees at midpoint, zero at closed,
  no constraint conflicts and first sampled lid/flap collision at step 0.5.
- Formatting and diff checks passed for both changed Rust files.

Evidence remains local in `target/headboard-comparison/live-ui.json`,
`live-mcp.json` and `live-*.png`. These probes exercise the existing UI and
command paths. The truncated-result status logic has a focused regression;
its rendered partial-result state has not been forced in the live fixture.
Individual refined-angle sweeps and continuous collision proofs remain outside
this qualification.

Further visual review found stale motion-preview transforms on return to the
document pose: the step label returned to zero but eight moving occurrences
kept their previous preview transforms. `moved` now removes an override when
the freshly solved placement equals the document placement. A focused Rust
regression exercises moved/returned/moved placements. The live UI probe also
asserts `ui.capture.pending_moves == 0` after returning to start and after
clicking the first (step-zero) collision; a slider move must produce nonzero
pending moves. This checks preview state as well as the displayed timeline.

Final rerun: the desktop rebuilt successfully after the preview fix (13m59s).
The focused preview regression passed, and the rebuilt desktop passed both
the live MCP probe and the full pointer-driven UI probe including preview
state assertions. Native screenshots show the scrubbed step 10 pose and the
closed step 0 pose after clicking the first collision; `ui.capture` reports
zero pending moves at the latter. The app is left open on this collision report.
No full CI or commit/push was performed.
