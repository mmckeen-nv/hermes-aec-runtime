import json
from pathlib import Path
import subprocess
import sys

from hermes_aec_runtime.flight_recorder import FlightRecorder, assess_training_quality, export_training_examples, make_trace


def _trace(**overrides):
    values = dict(
        request="Move the balcony at C:\\Users\\Mark\\secret.3dm with sk-abcdefghijk",
        route={"intent": "modify", "host": "rhino"},
        scene_subset={"objects": [{"id": "a", "name": "balcony"}]},
        transaction={"operations": [{"op": "transform", "targets": ["a"], "translation": [0, 1, 0]}]},
        timing={"elapsed_ms": 12}, tool_outcomes=[{"tool": "rhino_apply_operations", "success": True, "duration_ms": 8}],
        receipt={"status": "completed", "transaction_id": "tx-1", "authorization": "Bearer abcdefghijk"},
        verification={"status": "verified", "failed": []}, recovery={},
        model={"provider": "nvidia", "model": "nemotron"}, token_usage={"input_tokens": 10, "output_tokens": 4},
        created_at=1,
    )
    values.update(overrides)
    return make_trace(**values)


def test_trace_hashes_scene_redacts_and_deduplicates(tmp_path):
    trace = _trace()
    encoded = json.dumps(trace)
    assert "balcony" not in json.dumps(trace["scene_subset"])
    assert "sk-abcdefghijk" not in encoded and "Users" not in encoded
    assert trace["receipt"]["authorization"] == "[REDACTED]"
    journal = FlightRecorder(tmp_path / "trace.jsonl")
    assert journal.append(trace) is True
    assert journal.append(trace) is False
    assert list(journal.read()) == [trace]


def test_quality_rejects_unverified_script_and_transcript():
    trace = _trace(transaction={"operations": [{"op": "script"}]}, verification={"status": "failed", "failed": ["delta"]})
    okay, reasons = assess_training_quality(trace)
    assert not okay
    assert {"outcome_not_verified", "typed_transaction_required"} <= set(reasons)
    dirty = dict(trace, transcript="raw conversation")
    assert "raw_transcript_present" in assess_training_quality(dirty)[1]
    try:
        FlightRecorder("unused.jsonl").append(dirty)
    except ValueError as exc:
        assert "transcripts" in str(exc)
    else:
        raise AssertionError("raw transcript was accepted")


def test_export_accepts_only_verified_typed_examples(tmp_path):
    source, target = tmp_path / "traces.jsonl", tmp_path / "training.jsonl"
    recorder = FlightRecorder(source)
    recorder.append(_trace())
    recorder.append(_trace(request="bad", receipt={"status": "failed", "transaction_id": "tx-2"}))
    counts = export_training_examples(source, target)
    assert counts == {"accepted": 1, "rejected": 1}
    example = json.loads(target.read_text().strip())
    assert example["schema_version"] == "aec-tool-example/1.0"
    assert example["tool_call"]["operations"][0]["op"] == "transform"
    assert "messages" not in example and "transcript" not in example


def test_export_cli(tmp_path):
    source, target = tmp_path / "traces.jsonl", tmp_path / "out.jsonl"
    FlightRecorder(source).append(_trace())
    script = Path(__file__).parents[1] / "tools" / "export_training_data.py"
    result = subprocess.run([sys.executable, str(script), str(source), str(target)], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"accepted": 1, "rejected": 0}
    assert target.is_file()


def test_reader_ignores_interrupted_tail(tmp_path):
    path = tmp_path / "trace.jsonl"
    recorder = FlightRecorder(path); recorder.append(_trace())
    with path.open("a", encoding="utf-8") as stream: stream.write('{"interrupted":')
    assert len(list(recorder.read())) == 1
