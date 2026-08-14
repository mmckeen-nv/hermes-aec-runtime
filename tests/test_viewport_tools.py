import asyncio

import hermes_aec_runtime.mcp_server as server
from hermes_aec_runtime.rhinomcp_transport import RhinoMCPCommandError, RhinoMCPGateway


class ViewTransport:
    endpoint = "tcp://fake:1999"
    def __init__(self, commands=None):
        self.commands = commands if commands is not None else ["viewport_get_state", "viewport_orbit", "capture_viewport"]
        self.calls = []
    async def call(self, command, params=None, **_):
        self.calls.append((command, params or {}))
        if command == "describe_capabilities":
            return {"commands": self.commands}
        if command == "capture_viewport":
            return {"image_data": "iVBORw0KGgo=", "mime_type": "image/png"}
        return {"viewport_name": "Perspective", "camera": [1, 2, 3], "target": [0, 0, 0]}


def test_viewport_gateway_requires_advertised_native_command():
    gateway = RhinoMCPGateway(ViewTransport(commands=[]))
    try:
        asyncio.run(gateway.viewport_command("viewport_orbit", {}))
        assert False, "expected capability failure"
    except RhinoMCPCommandError as exc:
        assert "restart Rhino" in str(exc)


def test_viewport_orbit_is_typed_and_forwarded(monkeypatch):
    transport = ViewTransport(); gateway = RhinoMCPGateway(transport)
    monkeypatch.setattr(server, "_rhino_direct", gateway)
    result = asyncio.run(server.rhino_viewport_orbit(25, -10, (1, 1, 1)))
    assert result["viewport_name"] == "Perspective"
    assert transport.calls[-1] == ("viewport_orbit", {"azimuth_degrees": 25, "elevation_degrees": -10, "target": [1, 1, 1]})


def test_mcp_catalog_exposes_all_viewport_controls():
    names = {tool.name for tool in server.mcp._tool_manager.list_tools()}
    assert {
        "rhino_viewport_state", "rhino_viewport_zoom_extents", "rhino_viewport_set_camera",
        "rhino_viewport_set_target", "rhino_viewport_orbit",
        "rhino_viewport_restore_named_view", "rhino_viewport_capture",
    }.issubset(names)
