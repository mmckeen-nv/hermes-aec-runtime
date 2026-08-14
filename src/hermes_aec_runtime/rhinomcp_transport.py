"""Direct, deterministic transport for the RhinoMCP plugin TCP protocol.

The Hermes sidecar talks to this adapter; Hermes never receives RhinoMCP's large
tool catalogue.  Writes are deliberately never retried after bytes have been
sent.  An interrupted write is reconciled against a fresh scene instead.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
from dataclasses import dataclass, field
from hashlib import sha256
from time import perf_counter
from typing import Any, Awaitable, Callable, Mapping
from uuid import NAMESPACE_URL, uuid4, uuid5

from .operations import normalize_operations
from .rhinomcp_mapping import (
    RhinoMCPCommand,
    RhinoMCPMappingError,
    compile_rhinomcp_commands,
    scene_from_rhinomcp,
)

_HEADER_SIZE = 4
_MAX_FRAME_SIZE = 64 * 1024 * 1024
_READ_COMMANDS = {"describe_capabilities", "get_document_summary", "get_object_info", "get_objects"}


class RhinoMCPTransportError(RuntimeError):
    """The plugin protocol or connection failed."""


class RhinoMCPCommandError(RhinoMCPTransportError):
    """Rhino returned a structured command error."""


class RhinoMCPAmbiguousWrite(RhinoMCPTransportError):
    """A write may have executed but its response was lost."""


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        part = sock.recv(min(65536, length - len(chunks)))
        if not part:
            raise ConnectionResetError(f"Rhino closed the socket at {len(chunks)}/{length} bytes")
        chunks.extend(part)
    return bytes(chunks)


@dataclass
class RhinoMCPTransport:
    """One-command-per-connection framed TCP client.

    Short-lived sockets avoid carrying a poisoned connection across calls and
    make process ownership/restarts predictable.  Transaction serialization is
    owned by :class:`RhinoMCPGateway`.
    """

    host: str = field(default_factory=lambda: os.environ.get("HERMES_AEC_RHINOMCP_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.environ.get("HERMES_AEC_RHINOMCP_PORT", "1999")))
    timeout_seconds: float = field(default_factory=lambda: float(os.environ.get("HERMES_AEC_RHINOMCP_TIMEOUT", "60")))
    max_frame_size: int = _MAX_FRAME_SIZE

    @property
    def endpoint(self) -> str:
        return f"tcp://{self.host}:{self.port}"

    def _call_sync(self, command: str, params: Mapping[str, Any]) -> dict[str, Any]:
        envelope = {"type": command, "params": dict(params)}
        body = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(body) > self.max_frame_size:
            raise RhinoMCPTransportError(f"request frame exceeds {self.max_frame_size} bytes")
        sent = False
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout_seconds) as sock:
                sock.settimeout(self.timeout_seconds)
                sock.sendall(len(body).to_bytes(_HEADER_SIZE, "big") + body)
                sent = True
                header = _recv_exact(sock, _HEADER_SIZE)
                if header.startswith(b"{"):
                    raise RhinoMCPTransportError("plugin uses obsolete unframed protocol")
                length = int.from_bytes(header, "big")
                if length <= 0 or length > self.max_frame_size:
                    raise RhinoMCPTransportError(f"invalid Rhino response frame length {length}")
                raw = _recv_exact(sock, length)
        except (TimeoutError, socket.timeout, ConnectionError, OSError) as exc:
            if sent and command not in _READ_COMMANDS:
                raise RhinoMCPAmbiguousWrite(f"response lost after sending '{command}': {exc}") from exc
            raise RhinoMCPTransportError(f"RhinoMCP unavailable at {self.endpoint}: {exc}") from exc
        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if command not in _READ_COMMANDS:
                raise RhinoMCPAmbiguousWrite(f"invalid response after sending '{command}': {exc}") from exc
            raise RhinoMCPTransportError(f"invalid JSON response for '{command}': {exc}") from exc
        if not isinstance(response, dict):
            raise RhinoMCPTransportError(f"invalid response envelope for '{command}'")
        if response.get("status") != "success":
            raise RhinoMCPCommandError(str(response.get("message") or response.get("error") or f"{command} failed"))
        result = response.get("result", {})
        if isinstance(result, dict) and result.get("error"):
            raise RhinoMCPCommandError(str(result["error"]))
        if not isinstance(result, dict):
            raise RhinoMCPTransportError(f"'{command}' returned a non-object result")
        return result

    async def call(self, command: str, params: Mapping[str, Any] | None = None, *, read_attempts: int = 2) -> dict[str, Any]:
        attempts = max(1, read_attempts) if command in _READ_COMMANDS else 1
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                return await asyncio.to_thread(self._call_sync, command, params or {})
            except RhinoMCPTransportError as exc:
                last = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.1 * (2**attempt))
        assert last is not None
        raise last


LegacyExecutor = Callable[..., Awaitable[dict[str, Any]]]


class RhinoMCPGateway:
    """Serialized transaction gateway with receipts and lost-response recovery."""

    def __init__(self, transport: RhinoMCPTransport | None = None, *, legacy_executor: LegacyExecutor | None = None):
        self.transport = transport or RhinoMCPTransport()
        self.legacy_executor = legacy_executor
        self._lock = asyncio.Lock()
        self._receipts: dict[str, dict[str, Any]] = {}
        self._inflight: dict[str, asyncio.Future[dict[str, Any]]] = {}

    async def health(self) -> dict[str, Any]:
        started = perf_counter()
        try:
            caps = await self.transport.call("describe_capabilities", {})
            compatible = caps.get("protocol_version") == "aec-rhinomcp/1"
            return {"status": "healthy" if compatible else "incompatible", "endpoint": self.transport.endpoint,
                    "version": caps.get("version"), "command_count": caps.get("command_count", len(caps.get("commands", []))),
                    "protocol_version": caps.get("protocol_version"),
                    "required_protocol": "aec-rhinomcp/1",
                    "latency_ms": round((perf_counter() - started) * 1000, 3)}
        except Exception as exc:
            return {"status": "unavailable", "endpoint": self.transport.endpoint,
                    "error": str(exc), "latency_ms": round((perf_counter() - started) * 1000, 3)}

    async def scene_index(self, *, page_size: int = 500, max_objects: int = 10000) -> dict[str, Any]:
        if page_size < 1 or page_size > 2000 or max_objects < 1:
            raise ValueError("page_size must be 1..2000 and max_objects must be positive")
        async with self._lock:
            summary = await self.transport.call("get_document_summary", {})
            objects: list[dict[str, Any]] = []
            offset = 0
            truncated = False
            while len(objects) < max_objects:
                limit = min(page_size, max_objects - len(objects))
                page = await self.transport.call("get_objects", {"offset": offset, "limit": limit})
                batch = page.get("objects", [])
                if not isinstance(batch, list):
                    raise RhinoMCPTransportError("get_objects response has no objects array")
                objects.extend(item for item in batch if isinstance(item, dict))
                offset += len(batch)
                total = page.get("total_matching", page.get("total_count"))
                if not batch or len(batch) < limit or (isinstance(total, int) and offset >= total):
                    break
                if len(objects) >= max_objects:
                    truncated = True
            scene = scene_from_rhinomcp(summary, objects)
            scene["truncated"] = truncated
            scene["page_size"] = page_size
            return scene

    async def execute_operations(self, *, intent: str, operations: list[Mapping[str, Any]], dry_run: bool = True,
                                 idempotency_key: str | None = None,
                                 document_revision: str | None = None) -> dict[str, Any]:
        normalized = normalize_operations(operations)
        canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        fingerprint = sha256(canonical.encode()).hexdigest()
        key = idempotency_key or ""
        if key and key in self._receipts:
            prior = self._receipts[key]
            if prior["fingerprint"] == fingerprint:
                return {**prior, "replayed": True}
            return self._conflict(intent, key, fingerprint, prior)
        if key and key in self._inflight:
            prior = await asyncio.shield(self._inflight[key])
            return {**prior, "replayed": True, "concurrent_replay": True} if prior["fingerprint"] == fingerprint else self._conflict(intent, key, fingerprint, prior)
        future: asyncio.Future[dict[str, Any]] | None = None
        if key:
            future = asyncio.get_running_loop().create_future()
            self._inflight[key] = future
        try:
            receipt = await self._execute_once(
                intent, normalized, fingerprint, dry_run, key, document_revision
            )
            if key:
                self._receipts[key] = receipt
            if future and not future.done():
                future.set_result(receipt)
            return receipt
        except BaseException as exc:
            if future and not future.done():
                future.set_exception(exc); future.exception()
            raise
        finally:
            if key:
                self._inflight.pop(key, None)

    async def _execute_once(self, intent: str, operations: list[dict[str, Any]], fingerprint: str,
                            dry_run: bool, key: str,
                            document_revision: str | None) -> dict[str, Any]:
        transaction_id = str(uuid5(NAMESPACE_URL, key)) if key else str(uuid4())
        base = {"schema_version": "1.0", "transaction_id": transaction_id, "intent": intent, "fingerprint": fingerprint}
        try:
            commands = compile_rhinomcp_commands(operations)
        except RhinoMCPMappingError as exc:
            unsupported = {op["op"] for op in operations} & {"transform_in_place", "duplicate"}
            if self.legacy_executor is not None and unsupported and all(op["op"] in {"transform_in_place", "duplicate"} for op in operations):
                return await self.legacy_executor(intent=intent, operations=operations, dry_run=dry_run, idempotency_key=key or None)
            return {**base, "status": "blocked", "error": str(exc), "transport": "rhinomcp-direct"}
        if dry_run:
            return {**base, "status": "validated", "transport": "rhinomcp-direct",
                    "commands": [{"command": c.command, "params": c.params} for c in commands],
                    "evidence": ["typed operations valid", "all commands supported by RhinoMCP"]}

        async with self._lock:
            capabilities = await self.transport.call("describe_capabilities", {})
            protocol = capabilities.get("protocol_version")
            advertised = capabilities.get("commands", [])
            command_names = {
                str(item.get("name")) if isinstance(item, Mapping) else str(item)
                for item in advertised
            }
            required = {item.command for item in commands}
            if protocol != "aec-rhinomcp/1" or not required.issubset(command_names):
                missing = sorted(required - command_names)
                return {
                    **base,
                    "status": "blocked",
                    "transport": "rhinomcp-direct",
                    "error": "Rhino is not running the compatible hardened AEC RhinoMCP plugin",
                    "required_protocol": "aec-rhinomcp/1",
                    "observed_protocol": protocol,
                    "missing_commands": missing,
                    "created_ids": [], "modified_ids": [], "deleted_ids": [],
                }
            before = await self._scene_unlocked()
            if document_revision and before.get("document_revision") != document_revision:
                return {
                    **base,
                    "status": "blocked",
                    "transport": "rhinomcp-direct",
                    "error": "document revision changed after scene query",
                    "expected_document_revision": document_revision,
                    "current_document_revision": before.get("document_revision"),
                    "created_ids": [],
                    "modified_ids": [],
                    "deleted_ids": [],
                }
            aliases: dict[str, list[str]] = {}
            results: list[dict[str, Any]] = []
            ambiguous: Exception | None = None
            failed: Exception | None = None
            try:
                for command in commands:
                    params = _resolve_aliases(command.params, aliases)
                    result = await self.transport.call(command.command, params)
                    ids = _extract_ids(result, command.result_ids_field)
                    if command.bind:
                        if not ids:
                            raise RhinoMCPTransportError(f"{command.command} returned no IDs for ${command.bind}")
                        aliases.setdefault(command.bind, []).extend(ids)
                    results.append({"command": command.command, "params": params, "result": result})
            except RhinoMCPAmbiguousWrite as exc:
                ambiguous = exc
            except Exception as exc:
                failed = exc
            after = await self._scene_unlocked()
            before_objects = {str(item["id"]): item for item in before.get("objects", [])}
            after_objects = {str(item["id"]): item for item in after.get("objects", [])}
            created = sorted(after_objects.keys() - before_objects.keys())
            deleted = sorted(before_objects.keys() - after_objects.keys())
            modified = sorted(
                object_id for object_id in before_objects.keys() & after_objects.keys()
                if before_objects[object_id].get("content_hash") != after_objects[object_id].get("content_hash")
            )
            if ambiguous is not None and command.bind and command.result_ids_field in {"id", "result_id"}:
                already_bound = {value for values in aliases.values() for value in values}
                candidates = sorted(set(created) - already_bound)
                if len(candidates) == 1:
                    aliases[command.bind] = candidates
            expected_created = sorted({value for values in aliases.values() for value in values})
            after_ids = set(_ids(after))
            expected_deleted = {
                str(item["params"]["id"]) for item in results
                if item["command"] == "delete_object" and item["params"].get("id")
            }
            expected_existing = {
                str(item["params"]["id"]) for item in results
                if item["command"] in {"update_object_attributes", "transform_object_in_place"}
                and item["params"].get("id")
            }
            has_output_evidence = bool(expected_created or not any(item.bind for item in commands))
            verified = (has_output_evidence and all(value in after_ids for value in set(expected_created) | expected_existing)
                        and expected_existing.issubset(set(modified))
                        and all(value not in after_ids for value in expected_deleted))
            status = ("failed" if failed is not None else "completed" if ambiguous is None and verified
                      else "reconciled" if ambiguous is not None and verified else "unknown")
            receipt = {**base, "status": status, "transport": "rhinomcp-direct", "commands_completed": len(results),
                       "created_ids": created, "modified_ids": modified, "deleted_ids": deleted, "outputs": aliases,
                       "before_revision": before.get("document_revision"), "after_revision": after.get("document_revision"),
                       "verified": verified, "results": results}
            if failed:
                receipt["error"] = str(failed)
                receipt["recovery"] = "The batch may be partial. Inspect the observed GUID deltas and use Rhino Undo before retrying with a new key."
            if ambiguous:
                receipt["response_recovered"] = verified
                receipt["error"] = str(ambiguous)
                if not verified:
                    receipt["recovery"] = "Do not replay this key. Inspect the scene or undo before choosing a new key."
            return receipt

    async def _scene_unlocked(self) -> dict[str, Any]:
        summary = await self.transport.call("get_document_summary", {})
        objects: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self.transport.call("get_objects", {"offset": offset, "limit": 1000})
            batch = page.get("objects", [])
            if not isinstance(batch, list):
                raise RhinoMCPTransportError("get_objects response has no objects array")
            objects.extend(x for x in batch if isinstance(x, dict)); offset += len(batch)
            total = page.get("total_matching", page.get("total_count"))
            if not batch or len(batch) < 1000 or (isinstance(total, int) and offset >= total):
                break
        return scene_from_rhinomcp(summary, objects)

    @staticmethod
    def _conflict(intent: str, key: str, fingerprint: str, prior: dict[str, Any]) -> dict[str, Any]:
        return {"schema_version": "1.0", "transaction_id": str(uuid5(NAMESPACE_URL, key)), "status": "blocked",
                "intent": intent, "fingerprint": fingerprint, "error": "idempotency_key is already bound to a different payload",
                "prior_receipt": prior}


def _resolve_aliases(value: Any, aliases: Mapping[str, list[str]]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        values = aliases.get(value[1:])
        if not values or len(values) != 1:
            raise RhinoMCPTransportError(f"alias {value} must resolve to exactly one object")
        return values[0]
    if isinstance(value, list):
        answer: list[Any] = []
        for item in value:
            if isinstance(item, str) and item.startswith("$"):
                found = aliases.get(item[1:])
                if not found:
                    raise RhinoMCPTransportError(f"unresolved alias {item}")
                answer.extend(found)
            else:
                answer.append(_resolve_aliases(item, aliases))
        return answer
    if isinstance(value, dict):
        return {key: _resolve_aliases(item, aliases) for key, item in value.items()}
    return value


def _extract_ids(result: Mapping[str, Any], field: str | None) -> list[str]:
    if not field:
        return []
    value = result.get(field)
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    return [str(item) for item in values if item]


def _ids(scene: Mapping[str, Any]) -> list[str]:
    return [str(item.get("id")) for item in scene.get("objects", []) if item.get("id")]
