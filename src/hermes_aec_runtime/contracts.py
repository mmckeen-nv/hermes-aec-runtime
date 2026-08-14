from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SceneObject:
    id: str
    name: str
    kind: str
    layer: str = "Default"
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SceneIndex:
    document_id: str
    host: str
    units: str
    objects: tuple[SceneObject, ...]
    generated_at: str = field(default_factory=utc_now)
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AECAction:
    operation: str
    target_ids: tuple[str, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AECTransaction:
    request: str
    host: str
    actions: tuple[AECAction, ...]
    transaction_id: str = field(default_factory=lambda: str(uuid4()))
    dry_run: bool = True
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionReceipt:
    transaction_id: str
    status: str
    actions_attempted: int
    actions_completed: int
    evidence: tuple[str, ...] = ()
    error: str | None = None
    finished_at: str = field(default_factory=utc_now)
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

