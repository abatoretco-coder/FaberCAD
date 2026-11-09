# Product identity and prototype retirement

| Name | Meaning |
| --- | --- |
| FABER | Our customized version of SolidCraft; the product name shown to users. |
| FaberCAD | The active repository/directory name, not a separate application. |
| SolidCraft | The upstream CAD application and technical foundation. |
| Former FABER prototype | The separate Python/FreeCAD/Blender/agent project, retired locally. |

The active checkout is `D:\Projets\FaberCAD`, with origin
`https://github.com/abatoretco-coder/FaberCAD.git`. Start at the
[FABER documentation index](README.md). Codex remains a separate application using MCP.

## Compatibility names

Keep existing `solidcraft-*` crates and executable names, `.sc` files, commands,
environment variables, preference directories, keychain identifiers and MCP
configuration keys where they provide compatibility. Do not apply a global
search-and-replace to technical identifiers. They do not describe another
application the user needs to install. Preserve upstream licences and credits.

Public product headings, desktop display names and About use FABER, with
SolidCraft identified as the foundation. The [upstream README](../../README-SOLIDCRAFT.md)
and inherited technical references remain explicitly attributed to SolidCraft.

## Former prototype

On 2026-11-09 the owner requested local deletion of `D:\Projets\Faber` to free
space. It is distinct from this repository and the user's furniture projects at
`D:\Projets\meuble`. It is not a dependency of current FABER.

The former checkout was clean at commit
`7353df173bf3493193f5f229e2831537d57f8c2c`, branch `codex/cad-mcp-reset`,
origin `https://github.com/abatoretco-coder/Faber.git`. That remote is historical;
deleting or changing the GitHub repository is outside this local cleanup.

The initial recursive deletion was blocked by the execution policy. The owner
subsequently removed the prototype contents; the remaining empty directory was
removed after stopping auxiliary processes still attached to its working path.
That final cleanup verified that the active FABER repository and furniture
directory remained present. Earlier local receipts under `target/cleanup/` may
describe the initially blocked attempt rather than the final cleanup.

No duplicate local prototype backup was retained. Furniture sources and current
FABER trial artifacts were outside the deleted directory.

## Validation boundary

This cleanup does not compile or replace the existing executable. Source display
labels take effect after a future explicitly authorized build. Routine validation
remains [lightweight source CI](CI.md), which does not certify native behavior.
