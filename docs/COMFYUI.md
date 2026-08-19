# ComfyUI execution

The runtime owns the Blender-to-ComfyUI handoff. Hermes does not operate the ComfyUI browser and
does not submit ComfyUI operations through the Blender transaction compiler.

The normal sequence is:

1. Render a non-empty PNG through `blender_apply_operations`.
2. Call `comfyui_health`; require `status: ready` and a CUDA device.
3. Call `comfyui_stylize_image` once with absolute input/output paths, a geometry-preserving prompt,
   fixed dimensions, seed, and one stable idempotency key.
4. Require `status: completed`, `bytes`, `sha256`, `prompt_id`, and `output_path` from the receipt.

The gateway accepts only loopback HTTP, validates every required Flux 2 node and model before
submission, uploads a content-addressed source image, submits one fixed typed graph, polls its exact
prompt ID, downloads exactly one image, and atomically moves it to the requested new PNG path.
Once ComfyUI has accepted a prompt, failures are reported as `unknown` with the prompt ID so callers
do not blindly duplicate GPU work. Replays in the same runtime use the same idempotency receipt.

Defaults match the managed Windows ARM64 deployment:

- `flux-2-klein-base-4b-fp8.safetensors`
- `qwen_3_4b.safetensors`
- `flux2-vae.safetensors`
- `http://127.0.0.1:8188`

Set `HERMES_AEC_COMFYUI_URL` only to another loopback HTTP port. Remote ComfyUI endpoints are
intentionally rejected.
