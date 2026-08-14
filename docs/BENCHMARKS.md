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
