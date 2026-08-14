from hermes_aec_runtime.mcp_server import mcp
from hermes_aec_runtime.operation_models import CreateBox, SetAttributes, dump_operations


def test_rhino_tool_publishes_discriminated_operation_contract():
    tool = mcp._tool_manager.get_tool("rhino_apply_operations")
    schema = tool.parameters
    item = schema["properties"]["operations"]["items"]
    rendered = str(item)
    assert "discriminator" in item
    assert "create_box" in rendered
    assert "set_attributes" in rendered
    assert "targets" in schema["$defs"]["SetAttributes"]["properties"]
    assert "attributes" not in schema["$defs"]["CreateBox"]["properties"]


def test_typed_operations_dump_to_existing_compiler_shape():
    operations = dump_operations([
        CreateBox(op="create_box", id="post", min=(0, 0, 0), max=(1, 1, 2)),
        SetAttributes(op="set_attributes", targets=["$post"], name="POST", layer="SITE"),
    ])
    assert operations[0] == {"op": "create_box", "id": "post", "min": (0.0, 0.0, 0.0), "max": (1.0, 1.0, 2.0)}
    assert operations[1]["targets"] == ["$post"]


def test_set_attributes_accepts_rgb_and_rgba_with_bounded_channels():
    assert SetAttributes(op="set_attributes", targets=["object-id"], color=(10, 20, 30)).color == (10, 20, 30)
    assert SetAttributes(op="set_attributes", targets=["object-id"], color=(10, 20, 30, 128)).color == (10, 20, 30, 128)

    schema = mcp._tool_manager.get_tool("rhino_apply_operations").parameters
    rendered = str(schema["$defs"]["SetAttributes"]["properties"]["color"])
    assert "maxItems': 3" in rendered
    assert "maxItems': 4" in rendered
    assert "maximum': 255" in rendered
