---
name: flight-recorder
description: Capture sanitized, training-quality traces from typed AEC transactions. Use when benchmarking or preparing evaluation and fine-tuning datasets; never record raw prompts, transcripts, secrets, or full scene payloads.
---

# Flight Recorder

Record route, typed operation signature, receipt status, verification status, timing, retry count, and scene hashes. Record only hashes for scene snapshots and omit conversation text.

Export training data only through `tools/export_training_data.py`. Its gate admits completed, independently verified, typed traces; failed and ambiguous outcomes remain evaluation evidence rather than SFT examples.
