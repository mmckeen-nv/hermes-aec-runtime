import asyncio

from hermes_aec_runtime.mcp_server import mcp


def test_fast_path_and_all_typed_hosts_are_exposed():
    tools = {item.name for item in asyncio.run(mcp.list_tools())}
    assert {"aec_workflow_plan", "aec_run_workflow", "aec_runtime_health"} <= tools
    for host in ("rhino", "blender", "freecad"):
        assert f"{host}_scene_query" in tools
        assert f"{host}_apply_operations" in tools
