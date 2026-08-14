# End-to-end acceptance

The acceptance harness drives the same `aec_run_workflow` orchestration boundary used by Hermes. It exercises the real router, Rhino/Blender/FreeCAD transaction compilers, independent verification, workflow-memory promotion rules, and Flight Recorder. Only the external MCP connection is replaced with a deterministic stateful transport.

Run the safe suite from the repository root:

```powershell
python tools/run_acceptance.py --output .runtime/acceptance
```

The command runs 18 cases: create, in-place modification, delete, lost mutation response, stale document revision, and independent verification failure on each host. It exits nonzero on any mismatch and writes `acceptance-report.json` plus the rejected/promoted trace evidence.

## Optional live Rhino probe

The live check is intentionally impossible to trigger with a casual flag. It requires a running Rhino MCP, an environment opt-in, and an exact confirmation phrase. It creates one point, records its stable ID, deletes that exact ID in a `finally` cleanup, then proves that the complete document object-ID set equals the starting set.

```powershell
$env:HERMES_AEC_LIVE_ACCEPTANCE = "1"
python tools/run_acceptance.py --live-rhino --confirm I_ACCEPT_REVERSIBLE_RHINO_MUTATION
Remove-Item Env:HERMES_AEC_LIVE_ACCEPTANCE
```

Do not run the live mode while another actor is editing the document. A concurrent edit intentionally causes the zero-residue identity check to fail rather than concealing it.
