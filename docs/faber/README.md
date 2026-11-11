# FABER documentation

**FABER is our version of SolidCraft.** `FaberCAD` is the active repository and
directory name, not another application.

- [Project identity and prototype retirement](PROJECT-IDENTITY.md): naming,
  compatibility identifiers and the separate former prototype.
- [Product scope](SCOPE.md): dimensions, materials, assemblies, mechanisms,
  standard CAD parts and external MCP control.
- [Workshop](WORKSHOP.md): wood stock, materials, hardware and PLA.
- [Furniture catalogue](FURNITURE-CATALOGUE.md): 126 board/hardware recipes, plus native Workshop integration in source pending a future rebuild.
- [Design workflows](DESIGN-WORKFLOWS.md): woodworking, hardware and qualification limits.
- [MCP reference](../mcp.md): external automation.
- [Lightweight CI](CI.md): bounded source checks, no automatic native build.
- [Build status](BUILD.md): current Windows resource constraints.
- [Development-cost audit](DEVELOPMENT-AUDIT.md): measured bottlenecks and a staged reduction plan, without compilation.
- [Development mode](DEVELOPMENT-MODE.md): optional secondary importers and a plan-only selection without CPU rendering.
- [Targeted reconstruction plan](REBUILD-PLAN.md): strict limits and prerequisites; no compilation authorized or executed.
- [Reconstruction request policy](REBUILD-POLICY.md): exact local-unit authorization and fake-process regressions.
- [Cargo process gate](CARGO-GATE.md): Windows interception, including cached scripts; qualified with fake compilers, without Rust compilation.
- [Headboard motion](HEADBOARD-MOTION.md): real-project qualification fixture.

The [upstream README](../../README-SOLIDCRAFT.md), [architecture](../architecture.md)
and [upstream roadmap](../../ROADMAP.md) describe the inherited foundation.
Their release links and feature claims are not FABER release qualification.

Recent furniture trials are local artifacts under `target/`. Import and editing
checks do not certify strength, manufacturing readiness or untested mechanisms.
