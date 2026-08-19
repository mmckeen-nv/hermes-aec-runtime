"""Resilient Blender MCP gateway and Rhino-to-Blender handoff validation."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Awaitable, Callable, Protocol
from uuid import NAMESPACE_URL, uuid5

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .blender_operations import compile_blender_transaction
from .host_contract import blocked_stale, completed_receipt, content_hash, finalize_scene, lifecycle_receipt, recovery_plan as common_recovery_plan


class BlenderUnavailable(RuntimeError): pass


SCENE_QUERY_PROMPT = "Inspect the current Blender scene for deterministic AEC verification; do not modify it."
SCENE_MARKER = "HERMES_AEC_BLENDER_SCENE="
FULL_SCENE_SCRIPT = r'''import bpy, json, os
from mathutils import Vector
rows=[]
all_objects=list(bpy.data.objects)
for obj in all_objects[:5000]:
    corners=[obj.matrix_world @ Vector(corner) for corner in obj.bound_box] if obj.type=="MESH" else []
    bounds=None if not corners else [[min(p[i] for p in corners) for i in range(3)],[max(p[i] for p in corners) for i in range(3)]]
    rows.append({"id":obj.name,"name":obj.name,"type":obj.type,"collection":obj.users_collection[0].name if obj.users_collection else "Scene Collection","location":list(obj.location),"rotation":list(obj.rotation_euler),"scale":list(obj.scale),"bounds":bounds,"materials":[slot.material.name for slot in obj.material_slots if slot.material]})
print("HERMES_AEC_BLENDER_SCENE="+json.dumps({"document_id":bpy.data.filepath or "unsaved","units":"meters","process_id":os.getpid(),"total_objects":len(all_objects),"truncated":len(all_objects)>5000,"objects":rows},separators=(",",":")))
'''


def _tool_error(payload: Any) -> str | None:
    """Recognize BlenderMCP failures that are incorrectly returned as success text."""
    if isinstance(payload, dict):
        if str(payload.get("status", "")).lower() in {"error", "failed", "failure"}:
            return str(payload.get("error") or payload.get("message") or payload)
        for key in ("result", "content", "stdout"):
            error = _tool_error(payload.get(key)) if key in payload else None
            if error:
                return error
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            error = _tool_error(item)
            if error:
                return error
    elif isinstance(payload, str):
        text = payload.strip()
        if text.lower().startswith(("error executing", "error:", "execution error", "traceback (most recent call last)")):
            return text
    return None


def _scene_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Unwrap the success envelope emitted by current BlenderMCP releases."""
    error = _tool_error(payload)
    if error:
        raise BlenderUnavailable(error)
    result = payload.get("result")
    if isinstance(result, str):
        try:
            decoded = json.loads(result)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            return decoded
    if isinstance(result, dict):
        return result
    return payload


def _full_scene_payload(payload: Any) -> dict[str, Any]:
    error = _tool_error(payload)
    if error:
        raise BlenderUnavailable(error)
    strings: list[str] = []
    def collect(value: Any) -> None:
        if isinstance(value, str):
            strings.append(value)
            try: decoded = json.loads(value)
            except json.JSONDecodeError: decoded = None
            if decoded is not None and decoded != value: collect(decoded)
        elif isinstance(value, dict):
            for child in value.values(): collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value: collect(child)
    collect(payload)
    for text in strings:
        if SCENE_MARKER not in text:
            continue
        candidate = text.split(SCENE_MARKER, 1)[1].splitlines()[0].strip()
        try: decoded = json.loads(candidate)
        except json.JSONDecodeError: continue
        if isinstance(decoded, dict) and isinstance(decoded.get("objects"), list):
            return decoded
    raise BlenderUnavailable("Blender full-scene audit marker was missing")


def _finalize_blender_scene(payload: dict[str, Any]) -> dict[str, Any]:
    objects = []
    for raw in payload.get("objects", []):
        item = {
            "id": str(raw.get("id") or raw.get("name")), "name": str(raw.get("name", "")),
            "kind": str(raw.get("type", "UNKNOWN")), "layer": str(raw.get("collection", "Scene Collection")),
            "properties": {k: raw[k] for k in ("location", "rotation", "scale", "bounds", "materials") if k in raw},
        }
        item["content_hash"] = content_hash(item)
        objects.append(item)
    scene = finalize_scene(host="blender", document_id=str(payload.get("document_id", "unsaved")), units=str(payload.get("units", "meters")), objects=objects)
    scene["process_id"] = payload.get("process_id")
    scene["total_objects"] = int(payload.get("total_objects", len(objects)))
    scene["truncated"] = bool(payload.get("truncated"))
    return scene


class BlenderTransport(Protocol):
    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class StdioBlenderTransport:
    """Connect to the standard Blender MCP without exposing raw code to Hermes."""

    command: str = "uvx"
    args: tuple[str, ...] = ("blender-mcp",)

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        child_env = dict(os.environ)
        child_env.update({
            "DISABLE_TELEMETRY": "true", "BLENDER_MCP_DISABLE_TELEMETRY": "true",
            "MCP_DISABLE_TELEMETRY": "true", "HF_HUB_DISABLE_TELEMETRY": "1",
        })
        parameters = StdioServerParameters(command=self.command, args=list(self.args), env=child_env)
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)
        if result.isError:
            detail = " ".join(getattr(item, "text", "") for item in result.content)
            raise BlenderUnavailable(detail or f"Blender MCP tool {tool} failed")
        if result.structuredContent is not None:
            payload = dict(result.structuredContent)
            error = _tool_error(payload)
            if error: raise BlenderUnavailable(error)
            return payload
        texts = [getattr(item, "text", "") for item in result.content]
        if len(texts) == 1:
            try:
                decoded = json.loads(texts[0])
                payload = decoded if isinstance(decoded, dict) else {"result": decoded}
                error = _tool_error(payload)
                if error: raise BlenderUnavailable(error)
                return payload
            except json.JSONDecodeError:
                pass
        payload = {"content": texts}
        error = _tool_error(payload)
        if error: raise BlenderUnavailable(error)
        return payload


def default_transport() -> StdioBlenderTransport:
    command = os.environ.get("HERMES_AEC_BLENDER_COMMAND", "uvx")
    args = tuple(filter(None, os.environ.get("HERMES_AEC_BLENDER_ARGS", "blender-mcp").split()))
    return StdioBlenderTransport(command=command, args=args)


@dataclass
class BlenderGateway:
    transport_factory: Callable[[], BlenderTransport]
    read_attempts: int = 3
    timeout_seconds: float = 90
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _receipts: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)

    def has_receipt(self, idempotency_key: str) -> bool:
        return idempotency_key in self._receipts

    async def _call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.wait_for(self.transport_factory().call(tool, args), self.timeout_seconds)

    async def _read(self, operation: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        async with self._lock:
            error: Exception | None = None
            for attempt in range(self.read_attempts):
                try: return await operation()
                except Exception as exc:
                    error = exc
                    if attempt + 1 < self.read_attempts: await asyncio.sleep(.05 * 2**attempt)
            raise BlenderUnavailable(f"Blender read failed after {self.read_attempts} attempts: {error}")

    async def scene_preprocessing(self, *, user_prompt: str = SCENE_QUERY_PROMPT) -> dict[str, Any]:
        payload = await self._read(lambda: self._call("execute_blender_code", {"code": FULL_SCENE_SCRIPT, "user_prompt": user_prompt}))
        return _finalize_blender_scene(_full_scene_payload(payload))

    async def execute(self, *, intent: str, operations: list[dict[str, Any]], idempotency_key: str, dry_run: bool = False, document_revision: str | None = None) -> dict[str, Any]:
        if not idempotency_key.strip(): raise ValueError("idempotency_key is required")
        compiled = compile_blender_transaction(operations)
        fingerprint = content_hash({"intent": intent, "transaction": compiled.fingerprint})
        transaction_id = str(uuid5(NAMESPACE_URL, idempotency_key))
        prior = self._receipts.get(idempotency_key)
        if prior:
            if prior["fingerprint"] == fingerprint: return {**prior, "replayed": True}
            return lifecycle_receipt(host="blender", transaction_id=transaction_id, status="blocked", fingerprint=fingerprint, error="idempotency key is bound to another payload", prior_receipt=prior)
        if dry_run:
            return lifecycle_receipt(host="blender", transaction_id=transaction_id, status="validated", fingerprint=fingerprint, normalized=compiled.normalized)
        async with self._lock:
            # Re-check after acquiring the mutation lock. Another coroutine may
            # have completed while this one was waiting.
            prior = self._receipts.get(idempotency_key)
            if prior:
                if prior["fingerprint"] == fingerprint: return {**prior, "replayed": True, "concurrent_replay": True}
                return lifecycle_receipt(host="blender", transaction_id=transaction_id, status="blocked", fingerprint=fingerprint, error="idempotency key is bound to another payload", prior_receipt=prior)
            try:
                before = await self.scene_preprocessing_unlocked(user_prompt=intent)
                if document_revision is not None and before["document_revision"] != document_revision:
                    return blocked_stale(host="blender", transaction_id=transaction_id, expected=document_revision, current=before["document_revision"], fingerprint=fingerprint)
                result = await self._call("execute_blender_code", {"code": compiled.script, "user_prompt": intent})
                error = _tool_error(result)
                if error: raise BlenderUnavailable(error)
                after = await self.scene_preprocessing_unlocked(user_prompt=intent)
            except Exception as exc:
                receipt = lifecycle_receipt(host="blender", transaction_id=transaction_id, status="unknown", fingerprint=fingerprint, error=str(exc), recovery="Inspect and reconcile the scene; do not issue another mutation blindly.")
                self._receipts[idempotency_key] = receipt
                return receipt
            receipt = completed_receipt(host="blender", transaction_id=transaction_id, intent=intent, fingerprint=fingerprint, before=before, after=after, result=result)
            self._receipts[idempotency_key] = receipt
        return receipt

    async def scene_preprocessing_unlocked(self, *, user_prompt: str = SCENE_QUERY_PROMPT) -> dict[str, Any]:
        payload = await self._call("execute_blender_code", {"code": FULL_SCENE_SCRIPT, "user_prompt": user_prompt})
        return _finalize_blender_scene(_full_scene_payload(payload))


def validate_handoff_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate an explicit Rhino export manifest before Blender import."""
    errors: list[str] = []
    if manifest.get("schema_version") != "1.0": errors.append("schema_version must be 1.0")
    if manifest.get("source_host") != "rhino": errors.append("source_host must be rhino")
    if manifest.get("units") not in {"millimeters", "centimeters", "meters", "inches", "feet"}: errors.append("units must be explicit and supported")
    if not isinstance(manifest.get("export_path"), str) or not manifest.get("export_path", "").strip(): errors.append("export_path is required")
    objects = manifest.get("objects")
    if not isinstance(objects, list) or not objects: errors.append("objects must be a non-empty array")
    else:
        ids: set[str] = set()
        for i, obj in enumerate(objects):
            if not isinstance(obj, dict): errors.append(f"objects[{i}] must be an object"); continue
            for field in ("rhino_id", "layer"):
                if not isinstance(obj.get(field), str) or not obj[field].strip(): errors.append(f"objects[{i}].{field} is required")
            rid = obj.get("rhino_id")
            if rid in ids: errors.append(f"objects[{i}].rhino_id is duplicated")
            ids.add(rid)
    return {"valid": not errors, "errors": errors, "object_count": len(objects) if isinstance(objects, list) else 0, "unit_scale_to_meters": {"millimeters": .001, "centimeters": .01, "meters": 1, "inches": .0254, "feet": .3048}.get(manifest.get("units"))}


def recovery_plan(receipt: dict[str, Any]) -> dict[str, Any]:
    return common_recovery_plan(receipt, "Blender")
