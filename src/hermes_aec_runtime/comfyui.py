"""Typed, idempotent ComfyUI image-edit gateway for the AEC demo."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid4, uuid5


class ComfyUIError(RuntimeError):
    pass


class ComfyTransport(Protocol):
    async def health(self) -> dict[str, Any]: ...
    async def capabilities(self) -> dict[str, Any]: ...
    async def upload(self, path: Path, remote_name: str) -> dict[str, Any]: ...
    async def queue(self, prompt: dict[str, Any], client_id: str) -> dict[str, Any]: ...
    async def history(self, prompt_id: str) -> dict[str, Any]: ...
    async def download(self, *, filename: str, subfolder: str, kind: str) -> bytes: ...


def _loopback_url(value: str) -> str:
    parsed = urlparse(value.rstrip("/"))
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("ComfyUI URL must be loopback HTTP")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("ComfyUI URL must not include a path, query, or fragment")
    return value.rstrip("/")


@dataclass(frozen=True)
class HTTPComfyTransport:
    base_url: str = "http://127.0.0.1:8188"
    request_timeout: float = 30.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _loopback_url(self.base_url))

    def _json(self, path: str, *, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = Request(self.base_url + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=self.request_timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ComfyUIError(f"ComfyUI request failed for {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ComfyUIError(f"ComfyUI returned a non-object response for {path}")
        return payload

    async def health(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._json, "/system_stats")

    async def capabilities(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._json, "/object_info")

    async def upload(self, path: Path, remote_name: str) -> dict[str, Any]:
        boundary = "----hermes-aec-" + uuid4().hex
        data = path.read_bytes()
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{remote_name}\"\r\n"
            "Content-Type: image/png\r\n\r\n"
        ).encode("ascii") + data + (
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue"
            f"\r\n--{boundary}--\r\n"
        ).encode("ascii")
        request = Request(
            self.base_url + "/upload/image", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST",
        )

        def send() -> dict[str, Any]:
            try:
                with urlopen(request, timeout=self.request_timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                raise ComfyUIError(f"ComfyUI upload failed: {exc}") from exc
            if not isinstance(payload, dict) or not payload.get("name"):
                raise ComfyUIError("ComfyUI upload did not return an image name")
            return payload

        return await asyncio.to_thread(send)

    async def queue(self, prompt: dict[str, Any], client_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._json, "/prompt", body={"prompt": prompt, "client_id": client_id})

    async def history(self, prompt_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._json, f"/history/{prompt_id}")

    async def download(self, *, filename: str, subfolder: str, kind: str) -> bytes:
        query = urlencode({"filename": filename, "subfolder": subfolder, "type": kind})

        def receive() -> bytes:
            try:
                with urlopen(self.base_url + "/view?" + query, timeout=self.request_timeout) as response:
                    return response.read()
            except Exception as exc:
                raise ComfyUIError(f"ComfyUI output download failed: {exc}") from exc

        return await asyncio.to_thread(receive)


def default_transport() -> HTTPComfyTransport:
    return HTTPComfyTransport(os.environ.get("HERMES_AEC_COMFYUI_URL", "http://127.0.0.1:8188"))


def _required_model_values(capabilities: dict[str, Any], node: str, field_name: str) -> set[str]:
    try:
        values = capabilities[node]["input"]["required"][field_name][0]
    except (KeyError, IndexError, TypeError):
        return set()
    return {str(item) for item in values} if isinstance(values, list) else set()


def build_flux2_klein_edit_prompt(
    *, image_name: str, prompt: str, negative_prompt: str, seed: int,
    steps: int, width: int, height: int, filename_prefix: str,
    unet: str, clip: str, vae: str,
) -> dict[str, Any]:
    ref = lambda node, slot=0: [str(node), slot]
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip, "type": "flux2", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ref(3)}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_prompt, "clip": ref(3)}},
        "7": {"class_type": "VAEEncode", "inputs": {"pixels": ref(1), "vae": ref(4)}},
        "8": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ref(5), "latent": ref(7)}},
        "9": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ref(6), "latent": ref(7)}},
        "10": {"class_type": "CFGGuider", "inputs": {"model": ref(2), "positive": ref(8), "negative": ref(9), "cfg": 5.0}},
        "11": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "12": {"class_type": "Flux2Scheduler", "inputs": {"steps": steps, "width": width, "height": height}},
        "13": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "14": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "15": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ref(14), "guider": ref(10), "sampler": ref(11), "sigmas": ref(12), "latent_image": ref(13)}},
        "16": {"class_type": "VAEDecode", "inputs": {"samples": ref(15), "vae": ref(4)}},
        "17": {"class_type": "SaveImage", "inputs": {"images": ref(16), "filename_prefix": filename_prefix}},
    }


@dataclass
class ComfyUIGateway:
    transport: ComfyTransport
    poll_interval: float = 0.5
    timeout_seconds: float = 300.0
    unet: str = "flux-2-klein-base-4b-fp8.safetensors"
    clip: str = "qwen_3_4b.safetensors"
    vae: str = "flux2-vae.safetensors"
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _receipts: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)

    async def health(self) -> dict[str, Any]:
        stats = await self.transport.health()
        devices = stats.get("devices") if isinstance(stats.get("devices"), list) else []
        return {
            "status": "ready", "url": "loopback", "comfyui_version": stats.get("system", {}).get("comfyui_version"),
            "devices": [{"name": item.get("name"), "type": item.get("type")} for item in devices if isinstance(item, dict)],
        }

    def _validate(self, *, input_path: str, output_path: str, prompt: str, negative_prompt: str,
                  idempotency_key: str, seed: int, steps: int, width: int, height: int) -> tuple[Path, Path]:
        source = Path(input_path)
        destination = Path(output_path)
        if not source.is_absolute() or not source.is_file():
            raise ValueError("input_path must be an existing absolute image path")
        if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("input_path must be PNG, JPEG, or WebP")
        if source.stat().st_size > 100 * 1024 * 1024:
            raise ValueError("input image exceeds 100 MiB")
        if not destination.is_absolute() or destination.suffix.lower() != ".png":
            raise ValueError("output_path must be an absolute .png path")
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise ValueError("idempotency_key is required and must be at most 200 characters")
        if not prompt.strip() or len(prompt) > 4000 or len(negative_prompt) > 2000:
            raise ValueError("prompt is required and prompt limits are 4000/2000 characters")
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**64:
            raise ValueError("seed must be an unsigned 64-bit integer")
        if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 50:
            raise ValueError("steps must be between 1 and 50")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 256 or value > 2048 or value % 16 for value in (width, height)):
            raise ValueError("width and height must be multiples of 16 between 256 and 2048")
        return source, destination

    async def _materialize(self, entry: dict[str, Any], destination: Path, receipt: dict[str, Any]) -> dict[str, Any]:
        images = ((entry.get("outputs") or {}).get("17") or {}).get("images") or []
        if len(images) != 1 or not isinstance(images[0], dict):
            raise ComfyUIError("ComfyUI workflow did not produce exactly one output image")
        image = images[0]
        content = await self.transport.download(
            filename=str(image.get("filename", "")), subfolder=str(image.get("subfolder", "")), kind=str(image.get("type", "output")),
        )
        if len(content) < 1024:
            raise ComfyUIError("ComfyUI returned an empty or implausibly small image")
        if destination.exists() and destination.read_bytes() != content:
            raise ComfyUIError("output_path appeared during execution with different content")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)
        completed = {**receipt, "status": "completed", "output_path": str(destination), "bytes": len(content), "sha256": sha256(content).hexdigest()}
        completed.pop("error", None)
        completed.pop("recovery", None)
        return completed

    async def _reconcile(self, prior: dict[str, Any], destination: Path) -> dict[str, Any]:
        prompt_id = str(prior.get("prompt_id") or "")
        if prior.get("status") != "unknown" or not prompt_id:
            return prior
        history = await self.transport.history(prompt_id)
        entry = history.get(prompt_id)
        if not isinstance(entry, dict):
            return prior
        status = entry.get("status") or {}
        if status.get("status_str") == "error":
            failed = {**prior, "status": "failed", "error": f"ComfyUI workflow failed: {status.get('messages')}"}
            failed.pop("recovery", None)
            return failed
        if not status.get("completed"):
            return prior
        return await self._materialize(entry, destination, prior)

    async def stylize(self, *, input_path: str, output_path: str, prompt: str, idempotency_key: str,
                      negative_prompt: str = "distorted architecture, changed geometry, people, text, watermark, blurry, low quality",
                      seed: int = 0, steps: int = 20, width: int = 768, height: int = 512) -> dict[str, Any]:
        source, destination = self._validate(
            input_path=input_path, output_path=output_path, prompt=prompt, negative_prompt=negative_prompt,
            idempotency_key=idempotency_key, seed=seed, steps=steps, width=width, height=height,
        )
        fingerprint = sha256(json.dumps({
            "source": sha256(source.read_bytes()).hexdigest(), "output": str(destination), "prompt": prompt,
            "negative_prompt": negative_prompt, "seed": seed, "steps": steps, "width": width, "height": height,
            "models": [self.unet, self.clip, self.vae],
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        transaction_id = str(uuid5(NAMESPACE_URL, "comfyui:" + idempotency_key))
        prior = self._receipts.get(idempotency_key)
        if prior:
            if prior["fingerprint"] != fingerprint:
                return {"schema_version": "aec-comfyui-receipt/1.0", "host": "comfyui", "status": "blocked", "transaction_id": transaction_id, "error": "idempotency key is bound to another payload"}
            reconciled = await self._reconcile(prior, destination)
            self._receipts[idempotency_key] = reconciled
            return {**reconciled, "replayed": True}
        if destination.exists():
            raise ValueError("output_path already exists")

        async with self._lock:
            prior = self._receipts.get(idempotency_key)
            if prior:
                reconciled = await self._reconcile(prior, destination)
                self._receipts[idempotency_key] = reconciled
                return {**reconciled, "replayed": True, "concurrent_replay": True}
            started = time.monotonic()
            prompt_id: str | None = None
            try:
                capabilities = await self.transport.capabilities()
                required_nodes = {
                    "LoadImage", "UNETLoader", "CLIPLoader", "VAELoader", "CLIPTextEncode", "VAEEncode",
                    "ReferenceLatent", "CFGGuider", "KSamplerSelect", "Flux2Scheduler", "EmptyFlux2LatentImage",
                    "RandomNoise", "SamplerCustomAdvanced", "VAEDecode", "SaveImage",
                }
                missing_nodes = sorted(required_nodes - capabilities.keys())
                if missing_nodes:
                    raise ComfyUIError("ComfyUI is missing required nodes: " + ", ".join(missing_nodes))
                for node, field_name, model in (("UNETLoader", "unet_name", self.unet), ("CLIPLoader", "clip_name", self.clip), ("VAELoader", "vae_name", self.vae)):
                    if model not in _required_model_values(capabilities, node, field_name):
                        raise ComfyUIError(f"required model is unavailable: {model}")
                remote_name = f"hermes-aec-{sha256(source.read_bytes()).hexdigest()[:16]}{source.suffix.lower()}"
                upload = await self.transport.upload(source, remote_name)
                graph = build_flux2_klein_edit_prompt(
                    image_name=str(upload["name"]), prompt=prompt, negative_prompt=negative_prompt,
                    seed=seed, steps=steps, width=width, height=height,
                    filename_prefix=f"AEC_Cliff_House/{transaction_id}", unet=self.unet, clip=self.clip, vae=self.vae,
                )
                queued = await self.transport.queue(graph, transaction_id)
                prompt_id = str(queued.get("prompt_id") or "")
                if not prompt_id or queued.get("node_errors"):
                    raise ComfyUIError(f"ComfyUI rejected workflow: {queued.get('node_errors') or queued}")
                deadline = time.monotonic() + self.timeout_seconds
                entry: dict[str, Any] | None = None
                while time.monotonic() < deadline:
                    history = await self.transport.history(prompt_id)
                    candidate = history.get(prompt_id)
                    if isinstance(candidate, dict):
                        status = candidate.get("status") or {}
                        if status.get("completed"):
                            entry = candidate
                            break
                        if status.get("status_str") == "error":
                            raise ComfyUIError(f"ComfyUI workflow failed: {status.get('messages')}")
                    await asyncio.sleep(self.poll_interval)
                if entry is None:
                    raise TimeoutError(f"ComfyUI workflow did not finish within {self.timeout_seconds:g} seconds")
                receipt = await self._materialize(entry, destination, {
                    "schema_version": "aec-comfyui-receipt/1.0", "host": "comfyui", "status": "completed",
                    "transaction_id": transaction_id, "prompt_id": prompt_id, "fingerprint": fingerprint,
                    "input_path": str(source), "elapsed_seconds": round(time.monotonic() - started, 3),
                    "models": {"unet": self.unet, "clip": self.clip, "vae": self.vae},
                })
            except Exception as exc:
                receipt = {
                    "schema_version": "aec-comfyui-receipt/1.0", "host": "comfyui", "status": "unknown" if prompt_id else "failed",
                    "transaction_id": transaction_id, "prompt_id": prompt_id, "fingerprint": fingerprint, "error": str(exc),
                    "recovery": "Reconcile prompt_id before retrying with the same idempotency key." if prompt_id else "Correct readiness or validation and retry with a new key.",
                }
            self._receipts[idempotency_key] = receipt
            return receipt
