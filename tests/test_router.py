from hermes_aec_runtime.router import Intent, route_request


def test_routes_rhino_modification_to_three_stage_tool_path():
    route = route_request("Move the north balcony railing outward 500 mm")
    assert route.intent is Intent.MODIFY
    assert route.host == "rhino"
    assert route.tools == ("rhino_scene_query", "rhino_apply_operations", "rhino_verify_transaction")
    assert "balcony" in route.target_terms


def test_routes_rendering_to_blender():
    route = route_request("Render the house with evening lighting")
    assert route.intent is Intent.VISUALIZE
    assert route.host == "blender"
    assert route.tools[0] == "blender_scene_query"


def test_routes_code_question_to_web_without_mutation():
    route = route_request("Check the city pool barrier code")
    assert route.intent is Intent.RESEARCH
    assert route.needs_web is True
    assert route.mutates is False


def test_routes_recovery_before_normal_mutation():
    route = route_request("Recover the failed Blender handoff")
    assert route.intent is Intent.RECOVER
    assert route.stages[0] == "host_supervision"
