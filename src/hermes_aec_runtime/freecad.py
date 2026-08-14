"""Serialized typed gateway for the standard FreeCAD MCP server."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import os
from hashlib import sha256
from typing import Any, Callable, Protocol
from uuid import NAMESPACE_URL, uuid5

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .freecad_operations import compile_freecad_transaction
from .host_contract import blocked_stale, completed_receipt, content_hash, finalize_scene, lifecycle_receipt, recovery_plan as common_recovery_plan


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
            return await self._scene_query_unlocked()

    async def _scene_query_unlocked(self) -> dict[str, Any]:
        raw = await asyncio.wait_for(self.transport_factory().call("get_document_info", {}), self.timeout_seconds)
        source = raw.get("objects", raw.get("document", {}).get("objects", []))
        objects = []
        for item in source:
            name = str(item.get("name") or item.get("Name") or item.get("label") or item.get("Label") or "")
            stable_id = str(item.get("id") or item.get("uuid") or item.get("Name") or item.get("name") or "")
            normalized = {
                "id": stable_id, "name": str(item.get("label") or item.get("Label") or name),
                "kind": str(item.get("type") or item.get("TypeId") or "UNKNOWN"),
                "layer": str(item.get("group") or item.get("Group") or ""),
                "visible": bool(item.get("visible", item.get("Visibility", True))),
                "bounds": item.get("bounds") or item.get("BoundBox"),
            }
            normalized["content_hash"] = content_hash(normalized)
            objects.append(normalized)
        document = raw.get("document", {})
        return finalize_scene(host="freecad", document_id=str(document.get("id") or document.get("file") or document.get("name") or "unsaved"),
                              units=str(document.get("units") or raw.get("units") or "meters"), objects=objects, document=document)

    async def execute(self, *, intent: str, operations: list[dict[str, Any]], idempotency_key: str, dry_run: bool = False, document_revision: str | None = None) -> dict[str, Any]:
        if not idempotency_key.strip(): raise ValueError("idempotency_key is required")
        compiled = compile_freecad_transaction(operations); txid = str(uuid5(NAMESPACE_URL, idempotency_key))
        fingerprint = content_hash({"intent": intent, "transaction": compiled.fingerprint})
        prior = self._receipts.get(idempotency_key)
        if prior:
            if prior["fingerprint"] == fingerprint: return {**prior, "replayed":True}
            return lifecycle_receipt(host="freecad", transaction_id=txid, status="blocked", fingerprint=fingerprint, error="idempotency key is bound to another payload", prior_receipt=prior)
        if dry_run: return lifecycle_receipt(host="freecad", transaction_id=txid, status="validated", fingerprint=fingerprint, normalized=compiled.normalized)
        async with self._lock:
            prior = self._receipts.get(idempotency_key)
            if prior:
                if prior["fingerprint"] == fingerprint: return {**prior, "replayed":True, "concurrent_replay":True}
                return lifecycle_receipt(host="freecad", transaction_id=txid, status="blocked", fingerprint=fingerprint, error="idempotency key is bound to another payload", prior_receipt=prior)
            try:
                before = await self._scene_query_unlocked()
                if document_revision is not None and before["document_revision"] != document_revision:
                    return blocked_stale(host="freecad", transaction_id=txid, expected=document_revision, current=before["document_revision"], fingerprint=fingerprint)
                result = await asyncio.wait_for(self.transport_factory().call("execute_code", {"code":compiled.script}), self.timeout_seconds)
                after = await self._scene_query_unlocked()
            except Exception as exc:
                receipt = lifecycle_receipt(host="freecad", transaction_id=txid, status="unknown", fingerprint=fingerprint, error=str(exc), recovery="Inspect and reconcile the document; do not issue another mutation blindly.")
                self._receipts[idempotency_key] = receipt
                return receipt
            receipt = completed_receipt(host="freecad", transaction_id=txid, intent=intent, fingerprint=fingerprint, before=before, after=after, result=result)
            self._receipts[idempotency_key] = receipt
        return receipt


def freecad_recovery_plan(receipt: dict[str, Any]) -> dict[str, Any]:
    return common_recovery_plan(receipt, "FreeCAD")
