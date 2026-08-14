# RhinoMCP Direct Transport

The runtime uses the RhinoMCP plugin's structured TCP protocol as its primary
Rhino transport. Hermes talks only to the AEC sidecar and therefore sees the
small AEC operation contract, not RhinoMCP's broad tool catalogue.

## Data path

`Hermes -> AEC Runtime -> RhinoMCPGateway -> RhinoMCP plugin (TCP 1999) -> Rhino`

Set `HERMES_AEC_RHINOMCP_HOST` (default `127.0.0.1`),
`HERMES_AEC_RHINOMCP_PORT` (default `1999`), and
`HERMES_AEC_RHINOMCP_TIMEOUT` (default `60` seconds) when the defaults do not
fit the deployment. The transport accepts only four-byte big-endian
length-prefixed UTF-8 JSON frames and rejects oversized, malformed, unframed,
or non-object responses.

## Safety and recovery contract

- One gateway lock serializes scene reads and mutations against Rhino's UI
  document.
- Read commands reconnect and retry. Mutating commands are sent once only.
- If a mutation response is lost, the gateway re-reads the independently
  generated scene index. A unique created-object delta can reconcile a
  single-ID result. Otherwise the receipt is `unknown` and explicitly forbids
  replay under the same key.
- Process-local idempotency coalesces concurrent callers and replays completed,
  reconciled, failed, or unknown receipts without issuing another mutation.
- Receipts include content-derived before/after document revisions, observed
  created/deleted GUIDs, bound output GUIDs, command results, and verification.
- The bundled hardened plug-in implements stable-GUID transforms and typed
  duplication. An incompatible upstream plug-in fails the `aec-rhinomcp/1`
  capability handshake before any mutation is sent.

The legacy bridge is disabled by default. It is an explicit operator-only
compatibility option and is never used by a normal installation.

## Integration API

Use `RhinoMCPGateway.scene_index()` for bounded, paginated scene ingestion,
`health()` for an end-to-end plugin capability probe, and
`execute_operations()` for validated AEC operation batches. Dry runs compile
and expose commands without opening a socket for mutation.

The gateway deliberately does not expose arbitrary Rhino commands, Python,
C#, or RhinoScript.
