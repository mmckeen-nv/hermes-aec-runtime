from __future__ import annotations

import json
import os
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import uuid4

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def _text_payload(result: Any) -> dict[str, Any]:
    for item in result.content:
        if getattr(item, "type", None) == "text":
            try:
                return json.loads(item.text)
            except json.JSONDecodeError:
                return {"stdout": item.text, "error": None}
    return {"error": "Rhino MCP returned no text payload"}


@dataclass(frozen=True)
class RhinoClient:
    url: str = ""

    @property
    def endpoint(self) -> str:
        return self.url or os.environ.get("HERMES_AEC_RHINO_URL", "http://127.0.0.1:10500/")

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with streamable_http_client(self.endpoint) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
                payload = _text_payload(result)
                if result.isError:
                    raise RuntimeError(payload.get("error") or payload.get("stdout") or f"Rhino tool {name} failed")
                return payload

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
        payload = await self.call("list_objects", args)
        units_script = """import json
doc = __rhino_doc__
print(json.dumps({"document_id": str(doc.RuntimeSerialNumber), "name": doc.Name, "path": doc.Path, "units": str(doc.ModelUnitSystem), "absolute_tolerance": doc.ModelAbsoluteTolerance}))
"""
        metadata = await self.call("run_python", {"script": units_script})
        stdout = metadata.get("stdout", "").strip().splitlines()
        doc = json.loads(stdout[-1]) if stdout else {}
        return {
            "schema_version": "1.0",
            "host": "rhino",
            "document": doc,
            "count": payload.get("count", 0),
            "truncated": payload.get("truncated", False),
            "objects": payload.get("objects", []),
            "elapsed_ms": round((perf_counter() - started) * 1000, 3),
        }

    async def execute_python(
        self,
        *,
        intent: str,
        script: str,
        expected_change: str,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        transaction_id = str(uuid4())
        forbidden = ("RhinoDoc.ActiveDoc", "scriptcontext.doc", "rhinoscriptsyntax")
        violations = [token for token in forbidden if token in script]
        if violations:
            return {
                "schema_version": "1.0", "transaction_id": transaction_id, "status": "blocked",
                "intent": intent, "expected_change": expected_change,
                "error": "Use injected __rhino_doc__; forbidden APIs: " + ", ".join(violations),
            }
        if dry_run:
            try:
                compile(script, "<hermes-rhino-transaction>", "exec")
            except SyntaxError as exc:
                return {
                    "schema_version": "1.0", "transaction_id": transaction_id, "status": "blocked",
                    "intent": intent, "expected_change": expected_change, "error": str(exc),
                }
            return {
                "schema_version": "1.0", "transaction_id": transaction_id, "status": "validated",
                "intent": intent, "expected_change": expected_change,
                "evidence": ["python syntax valid", "document handle policy valid"],
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
after_attempt = {{str(o.Id) for o in doc.Objects}}
after = after_attempt
receipt = {{
    "schema_version": "1.0", "transaction_id": tx_id,
    "status": "failed" if error else "completed",
    "intent": {intent!r}, "expected_change": {expected_change!r},
    "before_count": len(before), "after_count": len(after),
    "created_ids": sorted(after - before), "deleted_ids": sorted(before - after),
    "attempted_created_ids": sorted(after_attempt - before),
    "rolled_back": False,
    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "error": error,
}}
print("HERMES_AEC_RECEIPT=" + json.dumps(receipt))
'''
        payload = await self.call("run_python", {"script": wrapper})
        stdout = payload.get("stdout", "")
        diagnostic = "\n".join(part for part in (stdout, payload.get("error") or "") if part)
        marker = "HERMES_AEC_RECEIPT="
        receipt_line = next((line for line in reversed(diagnostic.splitlines()) if line.startswith(marker)), None)
        if not receipt_line:
            return {
                "schema_version": "1.0", "transaction_id": transaction_id, "status": "failed",
                "intent": intent, "expected_change": expected_change,
                "error": payload.get("error") or "Rhino returned no execution receipt", "raw_stdout": stdout[-2000:],
            }
        receipt = json.loads(receipt_line[len(marker):])
        if receipt["status"] == "failed":
            rollback = await self.call("run_command", {"command": "_Undo"})
            count_payload = await self.call("run_python", {
                "script": "import json\nprint(json.dumps({'count': sum(1 for _ in __rhino_doc__.Objects)}))"
            })
            count_lines = count_payload.get("stdout", "").strip().splitlines()
            current_count = json.loads(count_lines[-1])["count"] if count_lines else -1
            receipt["rolled_back"] = current_count == receipt["before_count"]
            receipt["after_count"] = current_count
            receipt["rollback_output"] = rollback.get("stdout") or rollback.get("result") or "_Undo sent"
            if receipt["rolled_back"]:
                receipt["created_ids"] = []
                receipt["deleted_ids"] = []
        return receipt
