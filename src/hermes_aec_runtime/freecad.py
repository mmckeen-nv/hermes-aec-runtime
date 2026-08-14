"""Serialized typed gateway for the standard FreeCAD MCP server."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import os
from typing import Any, Callable, Protocol
from uuid import NAMESPACE_URL, uuid5

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .freecad_operations import compile_freecad_transaction


class FreeCADTransport(Protocol):
    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class StdioFreeCADTransport:
    command: str = "freecad-mcp"
    args: tuple[str, ...] = ()

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with stdio_client(StdioServerParameters(command=self.command, args=list(self.args))) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize(); result = await session.call_tool(tool, arguments)
        if result.isError:
            raise RuntimeError(" ".join(getattr(item, "text", "") for item in result.content))
        if result.structuredContent is not None: return dict(result.structuredContent)
        text = "\n".join(getattr(item, "text", "") for item in result.content)
        try:
            value = json.loads(text); return value if isinstance(value, dict) else {"result": value}
        except json.JSONDecodeError: return {"content": text}


def default_freecad_transport() -> StdioFreeCADTransport:
    return StdioFreeCADTransport(
        command=os.environ.get("HERMES_AEC_FREECAD_COMMAND", "freecad-mcp"),
        args=tuple(filter(None, os.environ.get("HERMES_AEC_FREECAD_ARGS", "").split())),
    )


@dataclass
class FreeCADGateway:
    transport_factory: Callable[[], FreeCADTransport] = default_freecad_transport
    timeout_seconds: float = 120
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _receipts: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)

    async def scene_query(self) -> dict[str, Any]:
        async with self._lock:
            raw = await asyncio.wait_for(self.transport_factory().call("get_document_info", {}), self.timeout_seconds)
        source = raw.get("objects", raw.get("document", {}).get("objects", []))
        objects = []
        for item in source:
            name = str(item.get("name") or item.get("Name") or item.get("label") or item.get("Label") or "")
            stable_id = str(item.get("id") or item.get("uuid") or item.get("Name") or item.get("name") or "")
            objects.append({
                "id": stable_id, "name": str(item.get("label") or item.get("Label") or name),
                "kind": str(item.get("type") or item.get("TypeId") or "UNKNOWN"),
                "layer": str(item.get("group") or item.get("Group") or ""),
                "visible": bool(item.get("visible", item.get("Visibility", True))),
                "bounds": item.get("bounds") or item.get("BoundBox"),
            })
        return {"schema_version":"freecad-scene-index/1.0", "host":"freecad", "document":raw.get("document", {}), "objects":objects, "count":len(objects)}

    async def execute(self, *, intent: str, operations: list[dict[str, Any]], idempotency_key: str, dry_run: bool = False) -> dict[str, Any]:
        if not idempotency_key.strip(): raise ValueError("idempotency_key is required")
        compiled = compile_freecad_transaction(operations); txid = str(uuid5(NAMESPACE_URL, idempotency_key))
        prior = self._receipts.get(idempotency_key)
        if prior:
            if prior["fingerprint"] == compiled.fingerprint: return {**prior, "replayed":True}
            return {"status":"blocked", "transaction_id":txid, "error":"idempotency key is bound to another payload"}
        if dry_run: return {"status":"validated", "transaction_id":txid, "fingerprint":compiled.fingerprint, "normalized":compiled.normalized}
        async with self._lock:
            prior = self._receipts.get(idempotency_key)
            if prior:
                if prior["fingerprint"] == compiled.fingerprint: return {**prior, "replayed":True, "concurrent_replay":True}
                return {"status":"blocked", "transaction_id":txid, "error":"idempotency key is bound to another payload", "prior_receipt":prior}
            try: result = await asyncio.wait_for(self.transport_factory().call("execute_code", {"code":compiled.script}), self.timeout_seconds)
            except Exception as exc:
                receipt = {"status":"unknown", "transaction_id":txid, "fingerprint":compiled.fingerprint, "error":str(exc), "recovery":"Inspect and reconcile the document; do not issue another mutation blindly."}
                self._receipts[idempotency_key] = receipt
                return receipt
            receipt = {"schema_version":"1.0", "host":"freecad", "status":"completed", "transaction_id":txid, "intent":intent, "fingerprint":compiled.fingerprint, "result":result}
            self._receipts[idempotency_key] = receipt
        return receipt


def freecad_recovery_plan(receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("status") == "unknown": return {"action":"reconcile", "steps":["Query the active document", "Check intended labels and bounds", "Retry only with the same idempotency key"]}
    if receipt.get("status") == "failed": return {"action":"verify_rollback", "steps":["Confirm the FreeCAD transaction aborted", "Re-query the document"]}
    return {"action":"verify", "steps":["Re-query changed objects", "Check shape validity, labels, bounds, and units"]}
