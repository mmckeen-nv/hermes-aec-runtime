from pathlib import Path
import os
import re
import shutil
import subprocess


ROOT = Path(__file__).parents[1]
TOOLS = {
    "aec_workflow_plan",
    "aec_run_workflow",
    "aec_runtime_health",
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


def test_release_metadata_versions_match():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    package = (ROOT / "src" / "hermes_aec_runtime" / "__init__.py").read_text(encoding="utf-8")
    project_version = re.search(r'^version = "([^"]+)"$', project, re.MULTILINE).group(1)
    package_version = re.search(r'^__version__ = "([^"]+)"$', package, re.MULTILINE).group(1)
    assert project_version == package_version == "0.8.12"


def test_registration_exposes_typed_surface_without_direct_host_escape():
    registration = (ROOT / "Register-Hermes.ps1").read_text(encoding="utf-8")
    for tool in TOOLS:
        assert f"- {tool}" in registration
    include = registration.split("tools:", 1)[1]
    assert "rhino_execute_python" not in registration
    assert "- run_python" not in include
    assert "- run_csharp" not in include
    assert "Hermes must never bypass the sidecar" in registration


def test_packaging_has_versioned_config_and_lifecycle_commands():
    installer = (ROOT / "Install.ps1").read_text(encoding="utf-8")
    assert "schema_version = 2" in installer
    assert 'HERMES_AEC_CONFIG_VERSION = "2"' in installer
    assert 'HERMES_AEC_RHINOMCP_PORT = "$RhinoPort"' in installer
    for filename in ("Doctor.ps1", "Install-RhinoMCP.ps1", "Uninstall.ps1", "doctor.sh", "uninstall.sh"):
        assert (ROOT / filename).is_file()
    assert (ROOT / "vendor" / "aec-rhinomcp-0.4.0-aec.2-windows.zip").is_file()
    plugin_installer = (ROOT / "Install-RhinoMCP.ps1").read_text(encoding="utf-8")
    assert "ca441fe8-afc4-43a4-bee5-53e65030d229" in plugin_installer
    assert "yak.exe" not in plugin_installer.casefold()
    doctor = (ROOT / "Doctor.ps1").read_text(encoding="utf-8")
    for contract_value in (
        "AEC RhinoMCP ($PluginGuid)",
        "aec-rhinomcp.rhp",
        "hermes-aec-install.json",
        "mmckeen-nv/aec-rhinomcp",
    ):
        assert contract_value in plugin_installer
        assert contract_value in doctor
    for command in ("aecmcpstart", "aecmcpstop", "aecmcptest", "aecmcpversion"):
        assert command in plugin_installer
        assert command in doctor
    assert 'HKCU:\\Software\\McNeel\\Rhinoceros\\8.0\\Plug-ins\\$PluginGuid' in plugin_installer
    assert 'New-ItemProperty -Path $RegistryPluginPath -Name "FileName"' in plugin_installer
    assert 'New-ItemProperty -Path $RegistryPath -Name "FileName"' in plugin_installer
    assert 'Get-ItemPropertyValue -Path $RegistryPath -Name "FileName"' in doctor
    assert "RHINOMCP_COMMANDS_REGISTERED" in plugin_installer


def test_windows_scripts_are_compatible_with_windows_powershell_51():
    for script in ROOT.rglob("*.ps1"):
        content = script.read_text(encoding="utf-8")
        assert "utf8NoBOM" not in content, f"PowerShell 7-only encoding in {script}"


def test_installer_bootstraps_python_without_trusting_the_windows_store_alias():
    installer = (ROOT / "Install.ps1").read_text(encoding="utf-8")
    assert "hermes\\hermes-agent\\venv\\Scripts\\python.exe" in installer
    assert "hermes\\bin\\uv.exe" in installer
    assert "uv.exe" in installer
    assert "python install 3.12" in installer
    assert "Get-Command python.exe -ErrorAction SilentlyContinue" in installer


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
        "model:\n  provider: test\n\nmcp_servers:\n  existing:\n    command: existing.exe\n  rhino:\n    url: http://127.0.0.1:10500/\n    tools:\n      include:\n        - run_python\n\ntools:\n  custom: keep-me\n",
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
    assert "HERMES_AEC_RHINOMCP_PORT" in updated
    assert "  rhino:" not in updated
    assert "run_python" not in updated
    backups = list((profile_root / ".hermes-aec-backups").glob("config.*.yaml"))
    assert len(backups) == 2
