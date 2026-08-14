# Hermes AEC Runtime

An independent sidecar that lets Hermes inspect and change Rhino models through a small, typed, transactional tool surface. It is deliberately separate from every demo repository.

Hermes gets four Rhino tools:

- `rhino_health` — confirm the host is ready.
- `rhino_scene_query` — find objects and obtain stable IDs, units, and document revision.
- `rhino_apply_operations` — apply one idempotent batch of typed geometry operations.
- `rhino_verify_transaction` — verify the resulting model delta and assertions.

Raw Rhino scripting and foreground computer control are not part of the normal workflow.

## Requirements

- Windows 11
- Python 3.11 or newer on `PATH`
- Hermes with MCP support
- Rhino with its MCP bridge listening on port `10500`

The runtime itself also installs on Linux, ready for future FreeCAD/Blender adapters.

## Windows: install and run

Open PowerShell in this folder and run:

```powershell
.\Install.ps1
```

That command creates an isolated `.venv`, installs the sidecar, writes versioned MCP configuration, registers both Cliff House Hermes profiles when present, and runs diagnostics. Restart Hermes after installation.

To check the installation at any time:

```powershell
.\Doctor.ps1
```

If Rhino is intentionally closed:

```powershell
.\Doctor.ps1 -AllowRhinoOffline
```

To register a different profile or port:

```powershell
.\Register-Hermes.ps1 -Profile "my-profile" -RhinoPort 10500
```

Registration is idempotent and leaves a one-time `config.yaml.hermes-aec-backup` beside each changed Hermes profile. The modification profile is typed-only. The Full Build profile also receives the transactional Python escape hatch needed for specialized annotations not yet represented by typed operations. Generated configuration and the install manifest live in `.runtime/` and use `schema_version: 1`.

To remove registration and generated installation files:

```powershell
.\Uninstall.ps1
```

Use `-KeepEnvironment` to unregister Hermes but retain `.venv` and `.runtime`.

## Linux: install

```bash
./install.sh
./doctor.sh --allow-rhino-offline
```

Import `.runtime/hermes-mcp.json` into Hermes, then restart Hermes. Run `./uninstall.sh` to remove generated files.

## Agent workflow

For every material change:

```text
health → focused scene query → one typed operation batch → transaction verification
```

Use the bundled skills under `skills/` to keep this sequence concise. A lost mutation response must be reconciled with the same idempotency key; it must not be resubmitted as new work.

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest
```

See [architecture](docs/ARCHITECTURE.md), [demo integration](docs/DEMO_INTEGRATION.md), and [stack acceptance](docs/STACK_ACCEPTANCE.md). Demo repositories should pin a released sidecar version and call its installer; they should not copy runtime source.
