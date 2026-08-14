from hermes_aec_runtime.runtime import assemble_transaction, execute_transaction, preprocess_scene, route_context


def test_vertical_slice_routes_pool_and_returns_receipt():
    scene = preprocess_scene({"host": "mock", "units": "meters", "objects": [
        {"id": "pool", "name": "Pool", "kind": "curve", "layer": "Site"},
        {"id": "roof", "name": "Roof", "kind": "mesh", "layer": "Building"},
    ]})
    selected = route_context("add a fence around the pool", scene)
    assert selected[0].id == "pool"
    tx = assemble_transaction("add a fence", "mock", "create_pool_fence", [selected[0].id], dry_run=False)
    receipt = execute_transaction(tx)
    assert receipt.status == "completed"
    assert receipt.actions_completed == 1


def test_unknown_host_stops_without_execution():
    tx = assemble_transaction("change model", "rhino", "arbitrary_action")
    receipt = execute_transaction(tx)
    assert receipt.status == "blocked"
    assert receipt.actions_attempted == 0

