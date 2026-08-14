from hermes_aec_runtime.supervisor import (
    Checkpoint,
    CheckpointStore,
    HostState,
    PortStatus,
    ProcessStatus,
    RecoveryAction,
    RhinoHostSupervisor,
)


class Probe:
    def __init__(self, process, port, ready):
        self.process = process
        self.port = port
        self.ready = ready

    def process_status(self):
        return self.process

    def port_status(self, port):
        assert port == 10500
        return self.port

    def mcp_ready(self):
        return self.ready


def supervisor(tmp_path, process, port, ready=False):
    return RhinoHostSupervisor(Probe(process, port, ready), CheckpointStore(tmp_path / "checkpoint.json"))


def test_ready_host_needs_no_action(tmp_path):
    subject = supervisor(tmp_path, ProcessStatus(True, 41), PortStatus(True, 41), True)
    plan = subject.recovery_plan()
    assert plan.state is HostState.READY
    assert plan.actions == (RecoveryAction.NONE,)


def test_crash_restarts_and_restores_checkpoint(tmp_path):
    subject = supervisor(tmp_path, ProcessStatus(False, exit_code=-1), PortStatus(False))
    subject.checkpoints.save(Checkpoint("C:/work/house.3dm", "doc-7", "42", "tx-9"))
    plan = subject.recovery_plan()
    assert plan.state is HostState.CRASHED
    assert plan.automatic is True
    assert plan.actions == (
        RecoveryAction.RESTART_RHINO,
        RecoveryAction.OPEN_CHECKPOINT,
        RecoveryAction.VERIFY_DOCUMENT,
        RecoveryAction.RECONCILE_TRANSACTION,
        RecoveryAction.RESUME,
    )


def test_foreign_port_owner_never_triggers_restart(tmp_path):
    subject = supervisor(tmp_path, ProcessStatus(True, 41), PortStatus(True, 99), False)
    plan = subject.recovery_plan()
    assert plan.state is HostState.PORT_CONFLICT
    assert plan.actions == (RecoveryAction.REQUEST_OPERATOR,)
    assert plan.automatic is False


def test_unknown_transaction_blocks_restart_even_after_crash(tmp_path):
    subject = supervisor(tmp_path, ProcessStatus(False, exit_code=-1), PortStatus(False))
    plan = subject.recovery_plan(pending_transaction_id="tx-unknown", pending_transaction_status="unknown")
    assert plan.state is HostState.RECONCILIATION_REQUIRED
    assert plan.actions == (RecoveryAction.RECONCILE_TRANSACTION,)
    assert plan.automatic is False


def test_checkpoint_round_trip(tmp_path):
    store = CheckpointStore(tmp_path / "nested" / "checkpoint.json")
    expected = Checkpoint("C:/work/house.3dm", "doc-1", "8", "tx-8", "2026-08-14T00:00:00+00:00")
    store.save(expected)
    assert store.load() == expected
    assert not (tmp_path / "nested" / "checkpoint.json.tmp").exists()


def test_clean_stop_starts_without_checkpoint(tmp_path):
    subject = supervisor(tmp_path, ProcessStatus(False), PortStatus(False))
    plan = subject.recovery_plan()
    assert plan.state is HostState.STOPPED
    assert plan.actions == (RecoveryAction.START_RHINO, RecoveryAction.RESUME)


def test_running_host_without_listener_waits(tmp_path):
    subject = supervisor(tmp_path, ProcessStatus(True, 41), PortStatus(False), False)
    plan = subject.recovery_plan()
    assert plan.state is HostState.STARTING
    assert plan.actions == (RecoveryAction.WAIT,)
