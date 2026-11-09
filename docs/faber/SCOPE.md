# FABER scope

FABER is our customized version of SolidCraft, developed in the `FaberCAD`
repository. The former standalone prototype is retired and is not a dependency.
See [project identity](PROJECT-IDENTITY.md) and [documentation index](README.md).

FABER is a deterministic CAD application with an external MCP interface. It contains no
embedded AI assistant, model runtime, or model-provider integration.

## Product capabilities

1. Parametric dimensions and constraints.
2. Physical materials and visual colours.
3. Components and assemblies.
4. Joints, limits, and movable mechanisms.
5. A parametric standard-parts catalogue plus linked STEP/CAD parts for assemblies.
6. MCP access to the same commands used by the desktop application and CLI.

## Codex boundary

Codex is a separate application and process. It connects to FABER through MCP exactly as
another external automation client would.

FABER may provide a small native integration surface for external Codex sessions:

- MCP server state and connection status;
- a copyable connection command or configuration;
- the external client's current selection or operation when supplied through MCP;
- grouped history entries, progress, errors, and undo for externally executed commands;
- an optional visual pointer or highlight identifying the geometry an external client is
  acting on.

This surface is not a chat panel and does not execute an AI model. FABER must not ship:

- Codex or another agent's source code;
- a model SDK or model-provider client;
- prompts, conversations, or agent orchestration;
- model API keys or AI authentication;
- direct network calls to an AI service.

The external Codex application owns its conversation, authentication, reasoning, and tool
selection. FABER owns only CAD state, deterministic commands, validation, history, and MCP
transport.

## Existing foundation

The SolidCraft fork already provides dimensions, materials, appearances, components,
assemblies, joints, motion, CAD import/export, and MCP control. FABER reuses those
capabilities instead of replacing them.

The upstream embedded assistant UI is not a FABER capability. FABER builds must omit it
while retaining the independent CLI and MCP server.

Secondary FCStd/Rhino decoders are now opt-in through `foreign-cad-import` in the
source configuration. STEP and native `.sc` support remain independent. The
[development selection](DEVELOPMENT-MODE.md) also omits optional CPU rendering;
its native qualification is pending, and the existing executable is unchanged.

## CAD catalogue in the MVP

FABER reuses the existing **Standard Parts** catalogue instead of introducing another library
system. It already creates editable CAD for metric and inch screws, bolts, nuts, washers, set
screws, dowel pins, and bearing envelopes. `parts.library`, `parts.insert`, and `parts.resize`
are deterministic engine commands and are therefore available through the desktop UI, CLI, and
MCP without a separate integration.

Other supplier or furniture parts use the existing STEP and linked-design import workflows.
The user keeps the source file and its usage rights; FABER does not download or redistribute
third-party CAD. A larger online supplier catalogue is deliberately outside the MVP.

The owner expanded the scope on 2026-11-08 with Workshop: nominal wood stock and
wood/PLA materials, procedural printable templates, A1-dependent geometric
preflight and the existing local slicer handoff. See [WORKSHOP.md](WORKSHOP.md).
This is not structural certification or a replacement slicer.

The woodworking follow-up adds actual-contact paired dowel drilling, a recomputed
local cutting list, and original generic furniture hardware with real joints.
See [DESIGN-WORKFLOWS.md](DESIGN-WORKFLOWS.md) for qualification scope and remaining
manufacturer-library and native-build gaps.

## Explicitly out of scope

- an embedded AI assistant rewrite;
- any embedded AI assistant, chat, model runtime, or agent orchestration;
- an online supplier marketplace, procurement, prices, stock, or delivery times;
- structural woodworking certification and automated machining/toolpaths;
- a replacement slicer, remote printer control or unattended physical printing;
- a new geometry kernel;
- a broad internal rename or file-format migration.
