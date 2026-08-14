from pathlib import Path
import os
import shutil
import subprocess


ROOT = Path(__file__).parents[1]
TOOLS = {
    "aec_workflow_plan",
    "aec_run_workflow",
    "route_aec_request",
    "rhino_health",
    "rhino_scene_query",
    "rhino_apply_operations",
    "rhino_verify_transaction",
    "blender_scene_query",
    "blender_apply_operations",
    "blender_validate_handoff",
    "blender_proof_and_recovery",
    "workflow_memory_promote",
    "workflow_memory_query",
    "flight_recorder_record",
}
SKILL_RHINO_TOOLS = {
    "aec_workflow_plan",
    "aec_run_workflow",
    "route_aec_request",
    "rhino_health",
    "rhino_scene_query",
    "rhino_apply_operations",
    "rhino_verify_transaction",
}


def test_registration_exposes_typed_surface_and_scoped_full_build_escape():
    registration = (ROOT / "Register-Hermes.ps1").read_text(encoding="utf-8")
    for tool in TOOLS:
        assert f"- {tool}" in registration
    include = registration.split("tools:", 1)[1]
    assert 'if ($Name -eq "cliff-house-full-build-windows")' in registration
    assert registration.count("rhino_execute_python") == 1
    assert "- run_python" not in include
    assert "- run_csharp" not in include


def test_packaging_has_versioned_config_and_lifecycle_commands():
    installer = (ROOT / "Install.ps1").read_text(encoding="utf-8")
    assert "schema_version = 1" in installer
    assert 'HERMES_AEC_CONFIG_VERSION = "1"' in installer
    for filename in ("Doctor.ps1", "Uninstall.ps1", "doctor.sh", "uninstall.sh"):
        assert (ROOT / filename).is_file()


def test_skills_name_only_the_typed_rhino_tools():
    skill_text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "skills").glob("*/SKILL.md"))
    for tool in SKILL_RHINO_TOOLS:
        assert tool in skill_text
    assert "rhino_execute_python" not in skill_text


def test_registration_is_atomic_idempotent_and_preserves_following_yaml(tmp_path):
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if not powershell:
        return
    profile = "packaging-test"
    profile_root = tmp_path / "hermes" / "profiles" / profile
    profile_root.mkdir(parents=True)
    config = profile_root / "config.yaml"
    config.write_text(
        "model:\n  provider: test\n\nmcp_servers:\n  existing:\n    command: existing.exe\n\ntools:\n  custom: keep-me\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(tmp_path)
    command = [
        powershell, "-NoProfile", "-File", str(ROOT / "Register-Hermes.ps1"),
        "-Profile", profile, "-RhinoPort", "10500",
    ]
    subprocess.run(command, check=True, env=env, capture_output=True, text=True)
    subprocess.run(command, check=True, env=env, capture_output=True, text=True)
    updated = config.read_text(encoding="utf-8-sig")
    assert updated.count("BEGIN HERMES AEC SIDECAR") == 1
    assert updated.index("  hermes_aec:") < updated.index("tools:")
    assert "custom: keep-me" in updated
    backups = list((profile_root / ".hermes-aec-backups").glob("config.*.yaml"))
    assert len(backups) == 2
