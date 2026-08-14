from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .contracts import AECTransaction, AECAction
from .runtime import assemble_transaction, execute_transaction, preprocess_scene, route_context

mcp = FastMCP("Hermes AEC Runtime")


@mcp.tool()
def scene_preprocessing(snapshot: dict) -> dict:
    """Normalize an AEC host snapshot into the compact SceneIndex contract."""
    return preprocess_scene(snapshot).to_dict()


@mcp.tool()
def request_context_routing(request: str, scene_index: dict, limit: int = 40) -> dict:
    """Return only scene objects relevant to a natural-language AEC request."""
    scene = preprocess_scene(scene_index)
    return {"request": request, "objects": [obj.__dict__ for obj in route_context(request, scene, limit)]}


@mcp.tool()
def action_assembly(
    request: str,
    host: str,
    operation: str,
    target_ids: list[str] | None = None,
    parameters: dict | None = None,
    dry_run: bool = True,
) -> dict:
    """Compile one explicit semantic operation into a reviewable AEC transaction."""
    return assemble_transaction(request, host, operation, target_ids or (), parameters, dry_run).to_dict()


@mcp.tool()
def proof_and_recovery(transaction: dict) -> dict:
    """Execute or validate an AEC transaction and return a durable receipt."""
    actions = tuple(AECAction(**action) for action in transaction["actions"])
    typed = AECTransaction(
        request=transaction["request"], host=transaction["host"], actions=actions,
        transaction_id=transaction["transaction_id"], dry_run=transaction.get("dry_run", True),
    )
    return execute_transaction(typed).to_dict()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

