import asyncio
import pytest

from hermes_aec_runtime.freecad import FreeCADGateway, freecad_recovery_plan
from hermes_aec_runtime.freecad_operations import FreeCADOperationError, compile_freecad_transaction
from hermes_aec_runtime.orchestrator import build_plan


class FakeTransport:
    def __init__(self, fail=False): self.fail=fail; self.calls=[]
    async def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        if self.fail: raise OSError("bridge lost")
        return {"objects":[{"name":"Wall"}]} if tool == "get_document_info" else {"ok":True}


def test_compiles_first_five_semantic_operations():
    result = compile_freecad_transaction([
        {"op":"create_box","id":"box","name":"Wall","length":4,"width":.2,"height":3},
        {"op":"create_cylinder","id":"post","radius":.05,"height":1.1,"position":[1,2,0]},
        {"op":"transform","target":"$box","translation":[1,0,0],"rotation_degrees":10},
        {"op":"set_attributes","target":"$box","label":"North Wall","group":"Walls","color":[.5,.5,.5]},
        {"op":"delete","target":"$post"},
    ])
    assert len(result.normalized) == 5
    assert "openTransaction" in result.script and "abortTransaction" in result.script


def test_rejects_unknown_fields_and_bad_aliases():
    with pytest.raises(FreeCADOperationError): compile_freecad_transaction([{"op":"create_box","id":"x","length":1,"width":1,"height":1,"oops":2}])
    with pytest.raises(FreeCADOperationError): compile_freecad_transaction([{"op":"delete","target":"$missing"}])


def test_gateway_scene_and_idempotent_mutation():
    transport=FakeTransport(); gateway=FreeCADGateway(lambda:transport)
    scene=asyncio.run(gateway.scene_query()); assert scene["count"] == 1
    kwargs={"intent":"wall", "operations":[{"op":"create_box","id":"w","length":1,"width":1,"height":1}], "idempotency_key":"request-wall"}
    first=asyncio.run(gateway.execute(**kwargs)); second=asyncio.run(gateway.execute(**kwargs))
    assert first["status"] == "completed" and second["replayed"] is True
    assert len([call for call in transport.calls if call[0] == "execute_code"]) == 1


def test_lost_response_is_unknown_and_requires_reconciliation():
    gateway=FreeCADGateway(lambda:FakeTransport(fail=True))
    receipt=asyncio.run(gateway.execute(intent="wall", operations=[{"op":"create_box","id":"w","length":1,"width":1,"height":1}], idempotency_key="lost"))
    assert receipt["status"] == "unknown"
    assert freecad_recovery_plan(receipt)["action"] == "reconcile"


def test_orchestrator_builds_freecad_plan_with_freecad_compiler():
    plan = build_plan("Build a FreeCAD wall", [{"op":"create_box","id":"wall","length":4,"width":.2,"height":3}], active_host="freecad")
    assert plan.route.host == "freecad"
    assert plan.normalized_transaction[0]["op"] == "create_box"
