from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .contracts import AECAction, AECTransaction, ExecutionReceipt, SceneIndex, SceneObject


def preprocess_scene(snapshot: dict[str, Any]) -> SceneIndex:
    """Normalize a host snapshot into a stable, compact scene index."""
    objects = tuple(
        SceneObject(
            id=str(item["id"]),
            name=str(item.get("name") or item["id"]),
            kind=str(item.get("kind", "unknown")),
            layer=str(item.get("layer", "Default")),
            properties=dict(item.get("properties", {})),
        )
        for item in snapshot.get("objects", [])
    )
    return SceneIndex(
        document_id=str(snapshot.get("document_id", "active-document")),
        host=str(snapshot.get("host", "mock")).lower(),
        units=str(snapshot.get("units", "unknown")),
        objects=objects,
    )


def route_context(request: str, scene: SceneIndex, limit: int = 40) -> tuple[SceneObject, ...]:
    """Cheap lexical routing; an adapter may later add spatial/semantic indexes."""
    words = {word.strip(".,:;()[]{}").lower() for word in request.split() if len(word) > 2}
    ranked = []
    for obj in scene.objects:
        haystack = f"{obj.name} {obj.kind} {obj.layer}".lower()
        score = sum(word in haystack for word in words)
        ranked.append((score, obj))
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    matched = [obj for score, obj in ranked if score > 0]
    return tuple((matched or [obj for _, obj in ranked])[:limit])


def assemble_transaction(
    request: str,
    host: str,
    operation: str,
    targets: Iterable[str] = (),
    parameters: dict[str, Any] | None = None,
    dry_run: bool = True,
) -> AECTransaction:
    if not operation or any(char.isspace() for char in operation):
        raise ValueError("operation must be a single explicit adapter operation name")
    action = AECAction(operation=operation, target_ids=tuple(targets), parameters=parameters or {})
    return AECTransaction(request=request, host=host.lower(), actions=(action,), dry_run=dry_run)


class MockAdapter:
    """Deterministic adapter used for deployment tests and contract development."""

    name = "mock"

    def execute(self, transaction: AECTransaction) -> ExecutionReceipt:
        evidence = tuple(
            f"{'validated' if transaction.dry_run else 'executed'}:{action.operation}:{len(action.target_ids)}"
            for action in transaction.actions
        )
        return ExecutionReceipt(
            transaction_id=transaction.transaction_id,
            status="validated" if transaction.dry_run else "completed",
            actions_attempted=len(transaction.actions),
            actions_completed=len(transaction.actions),
            evidence=evidence,
        )


def execute_transaction(transaction: AECTransaction) -> ExecutionReceipt:
    adapters = {"mock": MockAdapter()}
    adapter = adapters.get(transaction.host)
    if adapter is None:
        return ExecutionReceipt(
            transaction_id=transaction.transaction_id,
            status="blocked",
            actions_attempted=0,
            actions_completed=0,
            error=f"No configured adapter for host '{transaction.host}'",
        )
    return adapter.execute(transaction)

