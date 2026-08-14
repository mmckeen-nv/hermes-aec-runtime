# Acceptance benchmarks

The suite tests failure boundaries without requiring Rhino for normal development.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_acceptance.py -q
.\.venv\Scripts\python.exe -m benchmarks.run_acceptance --iterations 1000
```

The safe default performs scene selection, typed transaction compilation, and
independent verification with zero residue. Pytest adds read retries,
lost-response recovery, duplicate suppression, rollback, and host-down policy.

Live mode is read-only and requires two explicit signals:

```powershell
$env:HERMES_AEC_ALLOW_LIVE = "1"
.\.venv\Scripts\python.exe -m benchmarks.run_acceptance --live
```

Live mode checks MCP health and samples the scene. It never creates, modifies,
deletes, saves, restarts, or closes Rhino.

## One-call workflow latency

The host-free benchmark exercises the same route, compile, focused before
query, typed mutation, after query, and independent verification sequence used
by `aec_run_workflow`. It fails its process when p95 exceeds the supplied gate:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.run_workflow --iterations 500 --max-p95-ms 10
```

The mock number measures sidecar overhead, not Rhino/Blender/FreeCAD latency.
Store its JSON output in CI artifacts and compare like-for-like machines.

## Runtime metrics and readiness

Every one-call result includes `correlation_id` and a privacy-safe `metrics`
object with per-stage `duration_ms`, `budget_ms`, `status`, and exception class
only. The same correlation ID is written into its Flight Recorder trace.
Requests can tighten the default 30s query, 90s mutation, 30s verification and
150s total limits through `budget`; safety caps prevent unbounded execution.

Call `aec_runtime_health` without a host for process/storage readiness. Pass
`active_host` to include one bounded read probe. The response intentionally
discards host payloads and exception messages, returning only component state,
latency, and an error class.
