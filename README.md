# Hermes AEC Runtime

An independent sidecar that gives Hermes a fast, predictable way to operate AEC applications. It keeps model reasoning separate from host execution:

1. **Scene Pre-Processing** turns the active document into a compact scene index.
2. **Request Context Routing** selects only the relevant objects and rules.
3. **Action Assembly** compiles an approved intent into deterministic host actions.
4. **Proof and Recovery** executes, verifies, records a receipt, and stops safely on failure.

The sidecar does not contain the Cliff House demo and the demo does not contain this runtime. Their future integration is a small configuration layer.

## Requirements

- Windows 11 or Linux
- Python 3.11 or newer
- Hermes with MCP support
- An AEC host adapter (the included `mock` adapter works without Rhino, Blender, or FreeCAD)

## Install and run

Windows PowerShell:

```powershell
.\Install.ps1
.\Start.ps1
```

Linux/macOS:

```bash
./install.sh
./start.sh
```

The MCP server uses stdio. Add the generated entry from `.runtime/hermes-mcp.json` to the Hermes profile, then restart Hermes. Smoke-test without Hermes:

```powershell
.\.venv\Scripts\hermes-aec.exe doctor
.\.venv\Scripts\hermes-aec.exe demo
```

## Safety contract

- Every mutation is represented by an `AECTransaction` before execution.
- Every execution returns an `ExecutionReceipt` with evidence and timing.
- `dry_run` defaults to true.
- The sidecar never falls back to foreground UI automation.
- Host-specific behavior lives behind adapters; model prompts do not contain raw UI choreography.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/DEMO_INTEGRATION.md](docs/DEMO_INTEGRATION.md).

