# Demo Integration Boundary

The Cliff House demo remains in `aec_agent_versions`. This repository remains host- and project-independent.

Integration will add only:

1. A pinned sidecar release/version in the demo deployment script.
2. The `hermes_aec` MCP entry in each Hermes profile.
3. A demo adapter configuration identifying Rhino on Windows or FreeCAD on Linux.
4. Demo-specific project memory that names desired outcomes, never raw UI choreography.

Do not copy the runtime package or its skills into the demo repository. Install a released package and keep the repositories independently testable.

