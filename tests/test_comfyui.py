import asyncio
from pathlib import Path

import pytest

from hermes_aec_runtime.comfyui import ComfyUIGateway, HTTPComfyTransport, build_flux2_klein_edit_prompt


class FakeComfy:
    def __init__(self, *, missing_model=False, history_failures=0):
        models = {
            "UNETLoader": ("unet_name", ["flux-2-klein-base-4b-fp8.safetensors"]),
            "CLIPLoader": ("clip_name", ["qwen_3_4b.safetensors"]),
            "VAELoader": ("vae_name", [] if missing_model else ["flux2-vae.safetensors"]),
        }
        nodes = {
            "LoadImage", "CLIPTextEncode", "VAEEncode", "ReferenceLatent", "CFGGuider", "KSamplerSelect",
            "Flux2Scheduler", "EmptyFlux2LatentImage", "RandomNoise", "SamplerCustomAdvanced", "VAEDecode", "SaveImage",
        }
        self.caps = {name: {"input": {"required": {}}} for name in nodes}
        for node, (field, values) in models.items():
            self.caps[node] = {"input": {"required": {field: [values]}}}
        self.queue_calls = 0
        self.history_failures = history_failures

    async def health(self):
        return {"system": {"comfyui_version": "test"}, "devices": [{"name": "cuda:test", "type": "cuda"}]}

    async def capabilities(self):
        return self.caps

    async def upload(self, path, remote_name):
        return {"name": remote_name, "type": "input", "subfolder": ""}

    async def queue(self, prompt, client_id):
        self.queue_calls += 1
        assert prompt["3"]["inputs"]["type"] == "flux2"
        return {"prompt_id": "prompt-1", "node_errors": {}}

    async def history(self, prompt_id):
        if self.history_failures:
            self.history_failures -= 1
            raise RuntimeError("lost history response")
        return {prompt_id: {"status": {"completed": True, "status_str": "success"}, "outputs": {"17": {"images": [{"filename": "result.png", "subfolder": "AEC", "type": "output"}]}}}}

    async def download(self, **kwargs):
        return b"png" * 400


def test_stylize_writes_atomic_output_and_replays(tmp_path: Path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source image")
    destination = tmp_path / "out" / "result.png"
    transport = FakeComfy()
    gateway = ComfyUIGateway(transport, poll_interval=0, timeout_seconds=1)
    args = dict(input_path=str(source), output_path=str(destination), prompt="Preserve the house geometry", idempotency_key="same", seed=7)
    first = asyncio.run(gateway.stylize(**args))
    second = asyncio.run(gateway.stylize(**args))
    assert first["status"] == "completed"
    assert first["bytes"] == 1200
    assert destination.read_bytes() == b"png" * 400
    assert second["replayed"] is True
    assert transport.queue_calls == 1


def test_missing_model_fails_before_upload(tmp_path: Path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source image")
    gateway = ComfyUIGateway(FakeComfy(missing_model=True), poll_interval=0, timeout_seconds=1)
    receipt = asyncio.run(gateway.stylize(
        input_path=str(source), output_path=str(tmp_path / "result.png"), prompt="AEC", idempotency_key="missing",
    ))
    assert receipt["status"] == "failed"
    assert "flux2-vae.safetensors" in receipt["error"]


def test_same_key_reconciles_lost_response_without_duplicate_queue(tmp_path: Path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source image")
    destination = tmp_path / "result.png"
    transport = FakeComfy(history_failures=1)
    gateway = ComfyUIGateway(transport, poll_interval=0, timeout_seconds=1)
    args = dict(input_path=str(source), output_path=str(destination), prompt="AEC", idempotency_key="recover")
    first = asyncio.run(gateway.stylize(**args))
    second = asyncio.run(gateway.stylize(**args))
    assert first["status"] == "unknown"
    assert first["prompt_id"] == "prompt-1"
    assert second["status"] == "completed"
    assert second["replayed"] is True
    assert transport.queue_calls == 1


def test_validation_rejects_overwrite_and_bad_dimensions(tmp_path: Path):
    source = tmp_path / "source.png"
    destination = tmp_path / "result.png"
    source.write_bytes(b"source")
    destination.write_bytes(b"existing")
    gateway = ComfyUIGateway(FakeComfy())
    with pytest.raises(ValueError, match="already exists"):
        asyncio.run(gateway.stylize(input_path=str(source), output_path=str(destination), prompt="AEC", idempotency_key="x"))
    destination.unlink()
    with pytest.raises(ValueError, match="multiples of 16"):
        asyncio.run(gateway.stylize(input_path=str(source), output_path=str(destination), prompt="AEC", idempotency_key="x", width=777))


def test_workflow_has_reference_latent_and_save_node():
    graph = build_flux2_klein_edit_prompt(
        image_name="input.png", prompt="p", negative_prompt="n", seed=1, steps=20,
        width=768, height=512, filename_prefix="AEC/test", unet="u", clip="c", vae="v",
    )
    assert graph["8"]["class_type"] == "ReferenceLatent"
    assert graph["17"]["inputs"]["images"] == ["16", 0]


def test_http_transport_refuses_non_loopback():
    with pytest.raises(ValueError, match="loopback"):
        HTTPComfyTransport("https://example.com")
