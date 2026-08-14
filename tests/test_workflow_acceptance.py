from __future__ import annotations

import asyncio

import pytest

from hermes_aec_runtime.acceptance import run_deterministic_acceptance, run_live_rhino_acceptance
from hermes_aec_runtime.blender_operations import compile_blender_transaction


def test_all_host_workflow_acceptance_scenarios(tmp_path):
    report = asyncio.run(run_deterministic_acceptance(tmp_path))
    assert report["passed"] is True
    assert report["scenario_count"] == 18
    assert {(r["host"], r["scenario"]) for r in report["results"]} == {
        (host, scenario) for host in ("rhino", "blender", "freecad")
        for scenario in ("create", "modify", "delete", "lost_response", "stale_revision", "verification_failure")
    }
    assert all(r["transport_calls"][0]["method"] == "query" for r in report["results"])
    assert (tmp_path / "acceptance-report.json").exists()
    assert (tmp_path / "acceptance-flight.jsonl").exists()


def test_live_rhino_path_is_inert_without_double_opt_in(monkeypatch):
    monkeypatch.delenv("HERMES_AEC_LIVE_ACCEPTANCE", raising=False)
    with pytest.raises(PermissionError, match="requires"):
        asyncio.run(run_live_rhino_acceptance(confirmation="I_ACCEPT_REVERSIBLE_RHINO_MUTATION"))
    monkeypatch.setenv("HERMES_AEC_LIVE_ACCEPTANCE", "1")
    with pytest.raises(PermissionError, match="requires"):
        asyncio.run(run_live_rhino_acceptance(confirmation="yes"))


def test_blender_delete_is_a_real_typed_operation():
    compiled = compile_blender_transaction([{"op": "delete_objects", "objects": ["Acceptance Target"]}])
    assert compiled.normalized["operations"][0]["op"] == "delete_objects"
    assert "bpy.data.objects.remove" in compiled.script
