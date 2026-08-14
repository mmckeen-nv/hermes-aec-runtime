"""Rhino host lifecycle policy.

This module deliberately separates *deciding* what is safe from performing process
control.  A launcher may execute the returned actions, while tests and Hermes can
inspect the same recovery plan without ever killing Rhino.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class HostState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    CRASHED = "crashed"
    PORT_CONFLICT = "port_conflict"
    RECONCILIATION_REQUIRED = "reconciliation_required"


class RecoveryAction(StrEnum):
    NONE = "none"
    WAIT = "wait"
    RECONCILE_TRANSACTION = "reconcile_transaction"
    REQUEST_OPERATOR = "request_operator"
    START_RHINO = "start_rhino"
    RESTART_RHINO = "restart_rhino"
    OPEN_CHECKPOINT = "open_checkpoint"
    VERIFY_DOCUMENT = "verify_document"
    RESUME = "resume"


@dataclass(frozen=True)
class ProcessStatus:
    running: bool
    pid: int | None = None
    exit_code: int | None = None


@dataclass(frozen=True)
class PortStatus:
    listening: bool
    owner_pid: int | None = None


@dataclass(frozen=True)
class HostObservation:
    process: ProcessStatus
    port: PortStatus
    mcp_ready: bool
    pending_transaction_id: str | None = None
    pending_transaction_status: str | None = None


@dataclass(frozen=True)
class Checkpoint:
    document_path: str
    document_id: str
    document_revision: str
    transaction_id: str | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            object.__setattr__(self, "created_at", datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class RecoveryPlan:
    state: HostState
    actions: tuple[RecoveryAction, ...]
    reason: str
    checkpoint: Checkpoint | None = None
    automatic: bool = False


class HostProbe(Protocol):
    def process_status(self) -> ProcessStatus: ...
    def port_status(self, port: int) -> PortStatus: ...
    def mcp_ready(self) -> bool: ...


class ProcessController(Protocol):
    """Injectable executor; the policy never invokes this interface itself."""

    def start(self, document_path: str | None = None) -> int: ...
    def stop(self, pid: int) -> None: ...


class CheckpointStore:
    """Atomic JSON checkpoint metadata store (the .3dm is managed by the host)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def save(self, checkpoint: Checkpoint) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(asdict(checkpoint), indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def load(self) -> Checkpoint | None:
        if not self.path.exists():
            return None
        return Checkpoint(**json.loads(self.path.read_text(encoding="utf-8")))


class RhinoHostSupervisor:
    """Classifies host health and returns conservative, executable recovery plans."""

    def __init__(self, probe: HostProbe, checkpoint_store: CheckpointStore, port: int = 10500):
        self.probe = probe
        self.checkpoints = checkpoint_store
        self.port = port

    def observe(
        self,
        *,
        pending_transaction_id: str | None = None,
        pending_transaction_status: str | None = None,
    ) -> HostObservation:
        return HostObservation(
            process=self.probe.process_status(),
            port=self.probe.port_status(self.port),
            mcp_ready=self.probe.mcp_ready(),
            pending_transaction_id=pending_transaction_id,
            pending_transaction_status=pending_transaction_status,
        )

    def classify(self, observation: HostObservation) -> HostState:
        process, port = observation.process, observation.port
        if observation.pending_transaction_status == "unknown":
            return HostState.RECONCILIATION_REQUIRED
        if port.listening and (not process.running or (
            port.owner_pid is not None and process.pid is not None and port.owner_pid != process.pid
        )):
            return HostState.PORT_CONFLICT
        if process.running and port.listening and observation.mcp_ready:
            return HostState.READY
        if process.running and not port.listening:
            return HostState.STARTING
        if process.running:
            return HostState.DEGRADED
        if process.exit_code is not None:
            return HostState.CRASHED
        return HostState.STOPPED

    def plan(self, observation: HostObservation) -> RecoveryPlan:
        state = self.classify(observation)
        checkpoint = self.checkpoints.load()
        if state is HostState.READY:
            return RecoveryPlan(state, (RecoveryAction.NONE,), "Rhino MCP is ready", checkpoint, True)
        if state is HostState.RECONCILIATION_REQUIRED:
            return RecoveryPlan(
                state, (RecoveryAction.RECONCILE_TRANSACTION,),
                f"Transaction {observation.pending_transaction_id or 'unknown'} must be reconciled before host control",
                checkpoint, False,
            )
        if state is HostState.PORT_CONFLICT:
            return RecoveryPlan(
                state, (RecoveryAction.REQUEST_OPERATOR,),
                f"Port {self.port} is owned by a different or unknown process; automatic restart is unsafe",
                checkpoint, False,
            )
        if state in (HostState.STARTING, HostState.DEGRADED):
            return RecoveryPlan(state, (RecoveryAction.WAIT,), "Rhino is running but MCP is not ready", checkpoint, True)
        start = RecoveryAction.RESTART_RHINO if state is HostState.CRASHED else RecoveryAction.START_RHINO
        actions = [start]
        if checkpoint:
            actions.extend((RecoveryAction.OPEN_CHECKPOINT, RecoveryAction.VERIFY_DOCUMENT))
            if checkpoint.transaction_id:
                actions.append(RecoveryAction.RECONCILE_TRANSACTION)
        actions.append(RecoveryAction.RESUME)
        return RecoveryPlan(
            state, tuple(actions),
            "Rhino stopped unexpectedly" if state is HostState.CRASHED else "Rhino is not running",
            checkpoint, True,
        )

    def recovery_plan(
        self,
        *,
        pending_transaction_id: str | None = None,
        pending_transaction_status: str | None = None,
    ) -> RecoveryPlan:
        return self.plan(self.observe(
            pending_transaction_id=pending_transaction_id,
            pending_transaction_status=pending_transaction_status,
        ))
