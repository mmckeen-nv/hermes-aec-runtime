from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter
from typing import Any, AsyncIterator
from uuid import NAMESPACE_URL, uuid4, uuid5

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .scene_index import build_rhino_audit_script, parse_rhino_audit_output


class RhinoUnavailable(RuntimeError):
    """The Rhino bridge could not complete a request."""


def _text_payload(result: Any) -> dict[str, Any]:
    for item in result.content:
        if getattr(item, "type", None) == "text":
            try:
                return json.loads(item.text)
            except json.JSONDecodeError:
                return {"stdout": item.text, "error": None}
    return {"error": "Rhino MCP returned no text payload"}


_rhino_lock: asyncio.Lock | None = None
_rhino_lock_loop: asyncio.AbstractEventLoop | None = None
_recent_receipts: dict[str, dict[str, Any]] = {}
_metrics = {"connections": 0, "calls": 0, "reconnects": 0, "failures": 0}


def _lock() -> asyncio.Lock:
    global _rhino_lock, _rhino_lock_loop
    loop = asyncio.get_running_loop()
    if _rhino_lock is None or _rhino_lock_loop is not loop:
        _rhino_lock = asyncio.Lock()
        _rhino_lock_loop = loop
    return _rhino_lock


@dataclass(frozen=True)
class RhinoClient:
    url: str = ""
    timeout_seconds: float = 90.0
    read_attempts: int = 3

    @property
    def endpoint(self) -> str:
        return self.url or os.environ.get("HERMES_AEC_RHINO_URL", "http://127.0.0.1:10500/")

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ClientSession]:
        _metrics["connections"] += 1
        async with streamable_http_client(self.endpoint) as (read, write, _):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=15)
                yield session

    async def _call(self, session: ClientSession, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        _metrics["calls"] += 1
        result = await asyncio.wait_for(session.call_tool(name, arguments), timeout=self.timeout_seconds)
        payload = _text_payload(result)
        if result.isError:
            raise RhinoUnavailable(payload.get("error") or payload.get("stdout") or f"Rhino tool {name} failed")
        return payload

    async def _read_sequence(self, operation) -> Any:
        """Serialize Rhino UI access and safely retry an idempotent read sequence."""
        async with _lock():
            last_error: Exception | None = None
            for attempt in range(self.read_attempts):
                try:
                    async with self.session() as session:
                        return await operation(session)
                except Exception as exc:
                    last_error = exc
                    _metrics["failures"] += 1
                    if attempt + 1 < self.read_attempts:
                        _metrics["reconnects"] += 1
                        await asyncio.sleep(0.25 * (2**attempt))
            raise RhinoUnavailable(f"Rhino read failed after {self.read_attempts} attempts: {last_error}")

    async def health(self) -> dict[str, Any]:
        started = perf_counter()

        async def check(session: ClientSession) -> int:
            result = await asyncio.wait_for(session.list_tools(), timeout=15)
            return len(result.tools)

        try:
            tool_count = await self._read_sequence(check)
            return {
                "status": "healthy", "endpoint": self.endpoint, "rhino_tool_count": tool_count,
                "latency_ms": round((perf_counter() - started) * 1000, 3), **_metrics,
            }
        except Exception as exc:
            return {
                "status": "unavailable", "endpoint": self.endpoint,
                "latency_ms": round((perf_counter() - started) * 1000, 3), "error": str(exc), **_metrics,
            }

    async def scene_index(
        self,
        *,
        names: list[str] | None = None,
        layer: str | None = None,
        geometry_type: str | None = None,
        include_hidden: bool = True,
        limit: int = 5000,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"includeHidden": include_hidden, "includeLocked": True, "limit": limit}
        if names:
            args["names"] = names
        if layer:
            args["layer"] = layer
        if geometry_type:
            args["geometryType"] = geometry_type
        started = perf_counter()

        async def read(session: ClientSession) -> tuple[dict[str, Any], dict[str, Any]]:
            objects = await self._call(session, "list_objects", args)
            script = """import json
doc = __rhino_doc__
print(json.dumps({"document_id": str(doc.RuntimeSerialNumber), "name": doc.Name, "path": doc.Path, "units": str(doc.ModelUnitSystem), "absolute_tolerance": doc.ModelAbsoluteTolerance, "modified": doc.Modified}))
"""
            metadata = await self._call(session, "run_python", {"script": script})
            lines = metadata.get("stdout", "").strip().splitlines()
            return objects, (json.loads(lines[-1]) if lines else {})

        payload, doc = await self._read_sequence(read)
        return {
            "schema_version": "1.0", "host": "rhino", "document": doc,
            "count": payload.get("count", 0), "truncated": payload.get("truncated", False),
            "objects": payload.get("objects", []),
            "elapsed_ms": round((perf_counter() - started) * 1000, 3),
        }

    async def scene_query(self, *, query: dict[str, Any] | None = None, audit_limit: int = 2000) -> dict[str, Any]:
        """Run one rich bounded audit, then apply focused selectors locally."""
        started = perf_counter()
        script = build_rhino_audit_script(limit=audit_limit)

        async def read(session: ClientSession):
            payload = await self._call(session, "run_python", {"script": script})
            diagnostic = "\n".join(
                part for part in (payload.get("stdout", ""), payload.get("error") or "") if part
            )
            return parse_rhino_audit_output(diagnostic)

        index = await self._read_sequence(read)
        selected = index.query(**(query or {}))
        payload = dict(index.payload)
        selected_ids = {item["id"] for item in selected}
        payload["objects"] = selected
        payload["relationships"] = [
            edge for edge in payload["relationships"]
            if edge.get("source") in selected_ids or edge.get("target") in selected_ids
        ]
        payload["query"] = query or {}
        payload["query_count"] = len(selected)
        payload["indexed_count"] = index.payload.get("count", len(index.payload["objects"]))
        payload["elapsed_ms"] = round((perf_counter() - started) * 1000, 3)
        return payload

    async def document_revision(self) -> str:
        """Return the exact content-derived revision used by the rich audit."""
        scene = await self.scene_query(query={"limit": 1}, audit_limit=2000)
        return str(scene["document_revision"])

    async def save_checkpoint(self, path: str) -> dict[str, Any]:
        """Save the active working document after a completed transaction."""
        if not path.lower().endswith(".3dm"):
            raise ValueError("checkpoint path must end with .3dm")
        async with _lock():
            async with self.session() as session:
                return await self._call(session, "save_doc", {"path": path})

    async def _recover_receipt(self, transaction_id: str) -> dict[str, Any] | None:
        key = f"HermesAEC.{transaction_id}"

        async def read(session: ClientSession) -> dict[str, Any] | None:
            script = f'''import json
value = __rhino_doc__.Strings.GetValue({key!r})
print(value if value else "null")
'''
            payload = await self._call(session, "run_python", {"script": script})
            lines = payload.get("stdout", "").strip().splitlines()
            return json.loads(lines[-1]) if lines and lines[-1] != "null" else None

        try:
            return await self._read_sequence(read)
        except RhinoUnavailable:
            return None

    async def execute_python(
        self,
        *,
        intent: str,
        script: str,
        expected_change: str,
        dry_run: bool = True,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        transaction_id = str(uuid5(NAMESPACE_URL, idempotency_key)) if idempotency_key else str(uuid4())
        fingerprint = sha256(f"{intent}\0{script}\0{expected_change}".encode()).hexdigest()
        cached = _recent_receipts.get(idempotency_key or "")
        if cached:
            if cached.get("fingerprint") == fingerprint:
                return {**cached, "replayed": True}
            return {
                "schema_version": "1.0", "transaction_id": transaction_id, "status": "blocked",
                "intent": intent, "expected_change": expected_change, "fingerprint": fingerprint,
                "error": "idempotency_key is already bound to a different payload",
                "recovery": (
                    "The prior transaction rolled back; submit corrected code with a new unique key."
                    if cached.get("status") == "failed" and cached.get("rolled_back")
                    else "Do not change the payload for this key; inspect or verify the prior transaction."
                ),
                "prior_receipt": cached,
            }

        forbidden = ("RhinoDoc.ActiveDoc", "scriptcontext.doc", "rhinoscriptsyntax")
        violations = [token for token in forbidden if token in script]
        if violations:
            return {
                "schema_version": "1.0", "transaction_id": transaction_id, "status": "blocked",
                "intent": intent, "expected_change": expected_change,
                "error": "Use injected __rhino_doc__; forbidden APIs: " + ", ".join(violations),
            }
        try:
            compile(script, "<hermes-rhino-transaction>", "exec")
        except SyntaxError as exc:
            return {
                "schema_version": "1.0", "transaction_id": transaction_id, "status": "blocked",
                "intent": intent, "expected_change": expected_change, "error": str(exc),
            }
        if dry_run:
            return {
                "schema_version": "1.0", "transaction_id": transaction_id, "status": "validated",
                "intent": intent, "expected_change": expected_change, "fingerprint": fingerprint,
                "evidence": ["python syntax valid", "document handle policy valid"],
            }

        recovered = await self._recover_receipt(transaction_id) if idempotency_key else None
        if recovered:
            if recovered.get("fingerprint") == fingerprint:
                _recent_receipts[idempotency_key or ""] = recovered
                return {**recovered, "replayed": True}
            return {
                "schema_version": "1.0", "transaction_id": transaction_id, "status": "blocked",
                "intent": intent, "expected_change": expected_change, "fingerprint": fingerprint,
                "error": "idempotency_key is persisted for a different payload",
                "recovery": (
                    "The prior transaction rolled back; submit corrected code with a new unique key."
                    if recovered.get("status") == "failed" and recovered.get("rolled_back")
                    else "Verify the prior transaction; do not submit changed code with this key."
                ),
                "prior_receipt": recovered,
            }

        indented = "\n".join("    " + line for line in script.splitlines())
        wrapper = f'''import json, time, traceback
doc = __rhino_doc__
tx_id = {transaction_id!r}
before = {{str(o.Id) for o in doc.Objects}}
undo_id = doc.BeginUndoRecord("Hermes AEC: " + {intent!r}[:80])
started = time.perf_counter()
error = None
try:
{indented}
    doc.Views.Redraw()
except Exception:
    error = traceback.format_exc()
finally:
    if undo_id >= 0:
        doc.EndUndoRecord(undo_id)
after = {{str(o.Id) for o in doc.Objects}}
receipt = {{
    "schema_version": "1.0", "transaction_id": tx_id, "fingerprint": {fingerprint!r},
    "status": "failed" if error else "completed", "intent": {intent!r},
    "expected_change": {expected_change!r}, "before_count": len(before), "after_count": len(after),
    "created_ids": sorted(after - before), "deleted_ids": sorted(before - after),
    "attempted_created_ids": sorted(after - before), "rolled_back": False,
    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "error": error,
}}
serialized = json.dumps(receipt)
doc.Strings.SetString("HermesAEC." + tx_id, serialized)
print("HERMES_AEC_RECEIPT=" + serialized)
'''

        try:
            async with _lock():
                async with self.session() as session:
                    payload = await self._call(session, "run_python", {"script": wrapper})
        except Exception as exc:
            _metrics["failures"] += 1
            recovered = await self._recover_receipt(transaction_id)
            if recovered:
                recovered["response_recovered"] = True
                receipt = recovered
            else:
                return {
                    "schema_version": "1.0", "transaction_id": transaction_id, "status": "unknown",
                    "intent": intent, "expected_change": expected_change, "fingerprint": fingerprint,
                    "error": f"Rhino connection failed and receipt could not yet be reconciled: {exc}",
                    "recovery": "Retry with the same idempotency_key; never submit a new transaction blindly.",
                }
        else:
            diagnostic = "\n".join(part for part in (payload.get("stdout", ""), payload.get("error") or "") if part)
            marker = "HERMES_AEC_RECEIPT="
            line = next((value for value in reversed(diagnostic.splitlines()) if value.startswith(marker)), None)
            receipt = json.loads(line[len(marker):]) if line else await self._recover_receipt(transaction_id)
            if not receipt:
                return {
                    "schema_version": "1.0", "transaction_id": transaction_id, "status": "unknown",
                    "intent": intent, "expected_change": expected_change, "fingerprint": fingerprint,
                    "error": "Rhino returned no receipt; reconcile with the same idempotency_key.",
                }
            for output_line in diagnostic.splitlines():
                if output_line.startswith(marker):
                    continue
                try:
                    operation_result = json.loads(output_line)
                except json.JSONDecodeError:
                    continue
                if isinstance(operation_result, dict) and {
                    "created", "modified", "deleted"
                }.issubset(operation_result):
                    receipt["operation_result"] = operation_result
                    break

        if receipt["status"] == "failed":
            async with _lock():
                async with self.session() as session:
                    rollback = await self._call(session, "run_command", {"command": "_Undo"})
                    count_payload = await self._call(session, "run_python", {
                        "script": "import json\nprint(json.dumps({'count': sum(1 for _ in __rhino_doc__.Objects)}))"
                    })
            lines = count_payload.get("stdout", "").strip().splitlines()
            current_count = json.loads(lines[-1])["count"] if lines else -1
            receipt["rolled_back"] = current_count == receipt["before_count"]
            receipt["after_count"] = current_count
            receipt["rollback_output"] = rollback.get("stdout") or rollback.get("result") or "_Undo sent"
            if receipt["rolled_back"]:
                receipt["created_ids"] = []
                receipt["deleted_ids"] = []
        if idempotency_key:
            _recent_receipts[idempotency_key] = receipt
        return receipt
