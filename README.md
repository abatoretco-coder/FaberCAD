# FABER

**FABER is our customized version of SolidCraft**, focused on furniture, wood
assemblies and PLA parts. `FaberCAD` is this repository's name, not a second app.

The desktop application provides CAD dimensions, materials and colours, components,
assemblies, standard parts and mechanisms. Codex stays separate and controls FABER
through MCP; embedded AI is not part of the product scope.

- [Start here: FABER documentation](docs/faber/README.md)
- [Product identity and former prototype](docs/faber/PROJECT-IDENTITY.md)
- [Scope and limits](docs/faber/SCOPE.md)
- [Wood, materials and PLA workshop](docs/faber/WORKSHOP.md)
- [Design workflows and qualification status](docs/faber/DESIGN-WORKFLOWS.md)
- [External MCP reference](docs/mcp.md)

## Development and validation

Active checkout: `D:\Projets\FaberCAD`.
Origin: [abatoretco-coder/FaberCAD](https://github.com/abatoretco-coder/FaberCAD).
The former standalone prototype at `D:\Projets\Faber` is retired and is not a dependency.
User furniture source projects live separately under `D:\Projets\meuble`.

Routine validation is `python scripts/faber_ci.py`: changed-source checks bounded
at 180 seconds and 1 GiB. No automatic native build or large suite. See
[CI policy](docs/faber/CI.md), [build status](docs/faber/BUILD.md) and
[contributing](CONTRIBUTING.md). Source checks do not qualify an executable.

The existing desktop executable may lag source changes. Furniture imports do not
retain the original FreeCAD feature history; editing trials do not certify
strength, stability, manufacturing readiness or untested folding mechanisms.

## SolidCraft foundation

FABER is derived from SolidCraft, with upstream attribution and MIT OR Apache-2.0
licensing preserved. Technical crate/executable names, `.sc` files, MCP identifiers
and preference paths retain compatibility names where necessary.

- [Preserved upstream README](README-SOLIDCRAFT.md)
- [Inherited architecture](docs/architecture.md)
- [Upstream roadmap reference](ROADMAP.md)
- [Upstream project](https://github.com/tangency-labs/solidcraft)
- [MIT licence](LICENSE-MIT), [Apache-2.0 licence](LICENSE-APACHE) and [attribution](ATTRIBUTION.md)

Upstream downloads, releases and CI badges in inherited documents refer to
SolidCraft, not a released or qualified FABER build.
