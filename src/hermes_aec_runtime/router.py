from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Intent(StrEnum):
    INSPECT = "inspect"
    MODIFY = "modify"
    BUILD = "build"
    RESEARCH = "research"
    VISUALIZE = "visualize"
    HANDOFF = "handoff"
    RECOVER = "recover"


@dataclass(frozen=True)
class RequestRoute:
    intent: Intent
    host: str
    stages: tuple[str, ...]
    tools: tuple[str, ...]
    needs_web: bool
    mutates: bool
    risk: str
    target_terms: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "aec-request-route/1.0",
            "intent": self.intent.value,
            "host": self.host,
            "stages": list(self.stages),
            "tools": list(self.tools),
            "needs_web": self.needs_web,
            "mutates": self.mutates,
            "risk": self.risk,
            "target_terms": list(self.target_terms),
        }


_VERBS = {
    Intent.RECOVER: {"recover", "resume", "crashed", "failed", "rollback", "restore"},
    Intent.HANDOFF: {"handoff", "transfer", "export", "import"},
    Intent.VISUALIZE: {"render", "camera", "lighting", "visualize", "material"},
    Intent.RESEARCH: {"code", "ordinance", "zoning", "regulation", "product", "manufacturer"},
    Intent.BUILD: {"build", "construct", "generate", "assemble"},
    Intent.MODIFY: {"add", "change", "move", "delete", "remove", "replace", "resize", "rotate", "offset"},
    Intent.INSPECT: {"inspect", "audit", "find", "show", "measure", "list", "check", "explain"},
}

_STOP = {
    "the", "a", "an", "to", "of", "in", "on", "for", "with", "and", "or", "please",
    "this", "that", "model", "scene", "rhino", "blender", "make", "need", "want",
}


def route_request(request: str, *, active_host: str = "rhino") -> RequestRoute:
    if not isinstance(request, str):
        raise ValueError("request must be a string")
    if not isinstance(active_host, str) or active_host.casefold() not in {"rhino", "blender", "freecad"}:
        raise ValueError("active_host must be rhino, blender, or freecad")
    if len(request) > 64_000:
        raise ValueError("request exceeds 64000 characters")
    words = tuple(word.strip(".,:;!?()[]{}").casefold() for word in request.split())
    word_set = set(words)
    host = "blender" if "blender" in word_set or word_set & _VERBS[Intent.VISUALIZE] else active_host.casefold()
    scores = {intent: len(word_set & terms) for intent, terms in _VERBS.items()}
    priority = (Intent.RECOVER, Intent.HANDOFF, Intent.VISUALIZE, Intent.BUILD, Intent.MODIFY, Intent.RESEARCH, Intent.INSPECT)
    intent = max(priority, key=lambda value: (scores[value], -priority.index(value)))
    if scores[Intent.RESEARCH] and not (scores[Intent.BUILD] or scores[Intent.MODIFY]):
        intent = Intent.RESEARCH
    if scores[intent] == 0:
        intent = Intent.INSPECT
    needs_web = bool(word_set & _VERBS[Intent.RESEARCH])
    mutates = intent in {Intent.MODIFY, Intent.BUILD, Intent.VISUALIZE, Intent.HANDOFF, Intent.RECOVER}
    risk = "destructive" if word_set & {"delete", "remove", "replace", "overwrite"} else "mutation" if mutates else "read_only"

    if intent is Intent.RECOVER:
        stages = ("host_supervision", "receipt_reconciliation", "proof_and_recovery")
        tools = (f"{host}_health", "runtime_recovery_plan")
    elif intent is Intent.HANDOFF:
        stages = ("scene_preprocessing", "handoff_validation", "blender_control", "proof_and_recovery")
        source_host = active_host.casefold()
        tools = (f"{source_host}_scene_query", "blender_validate_handoff", "blender_apply_operations", "blender_proof_and_recovery")
    elif intent is Intent.VISUALIZE:
        stages = ("scene_preprocessing", "action_assembly", "blender_control", "proof_and_recovery")
        tools = ("blender_scene_query", "blender_apply_operations", "blender_proof_and_recovery")
    elif intent is Intent.RESEARCH:
        stages = ("scene_preprocessing", "aec_research", "request_context_routing")
        tools = (f"{host}_scene_query", "web")
    elif mutates:
        stages = ("scene_preprocessing", "action_assembly", f"{host}_control", "proof_and_recovery")
        tools = (f"{host}_scene_query", f"{host}_apply_operations", f"{host}_verify_transaction")
    else:
        stages = ("scene_preprocessing",)
        tools = (f"{host}_scene_query",)

    targets = tuple(dict.fromkeys(word for word in words if len(word) > 2 and word not in _STOP and all(word not in terms for terms in _VERBS.values())))
    return RequestRoute(intent, host, stages, tools, needs_web, mutates, risk, targets[:12])
