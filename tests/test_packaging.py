from pathlib import Path


ROOT = Path(__file__).parents[1]
TOOLS = {
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
    for tool in TOOLS:
        assert tool in skill_text
    assert "rhino_execute_python" not in skill_text
