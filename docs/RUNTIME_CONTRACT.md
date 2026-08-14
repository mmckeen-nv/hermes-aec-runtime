# AEC Runtime Contract 1.0.0

This contract is the stable boundary between Hermes, host adapters, workflow memory, the flight recorder, and demo profiles. Host-specific APIs may change without changing this boundary.

## Required flow

`scene_index → request_route → operation_transaction → execution_receipt → verification_result`

Every artifact uses the common envelope: `schema_version`, `kind`, globally unique `id`, and Unix epoch `created_at` in milliseconds. All mutations include the scene's exact `document_revision` and a stable `idempotency_key`. A stale revision must fail before mutation. Reusing a key returns the persisted receipt and never repeats geometry.

## Lifecycle

Allowed state transitions are:

- `planned → validated | failed`
- `validated → executing | failed`
- `executing → completed | failed | unknown`
- `unknown → completed | failed | rolled_back`
- `failed → rolled_back`

`completed` and `rolled_back` are terminal. A lost response is `unknown`, not `failed`; recovery reconciles the persisted receipt using the same key. A corrected mutation receives a new key. Verification is independent of execution.

## Budgets

Every evaluation and mutation declares positive limits for tool calls, elapsed milliseconds, input/output tokens, operations, and arbitrary-script bytes. Counters are cumulative and fail closed once any limit is exceeded. Default interactive limits are 8 calls, 120 seconds, 64k input tokens, 8k output tokens, 64 operations, and 64 KiB of script.

## Safety invariants

- Revision and idempotency key are mandatory for mutations.
- Mutations execute serially in one host transaction.
- Failure rolls back by default.
- Arbitrary scripts are disabled by default and are never silently substituted for typed operations.
- Successful mutation requires a verification result.
- Receipts enumerate created, modified, and deleted stable IDs.
- Trace payloads are hash-addressed and redact credentials, user paths, and document content marked private.

## Schemas

The `schemas` directory is normative. It contains rich scene index, route, transaction, receipt, verification, budget, safety, trace, and evaluation task/result schemas. Draft 2020-12 relative references resolve from that directory. Fixtures are deterministic, offline evaluation inputs.

## Versioning and migration

Versions use SemVer. Additive optional fields increment MINOR. Clarifications and schema fixes that do not change accepted documents increment PATCH. Removing, renaming, changing meaning, adding required fields, or changing units increments MAJOR.

A consumer accepts a producer with the same MAJOR and a MINOR no newer than its own. Unknown optional fields must be preserved by relays. Migration is explicit and pure: read old artifact, produce a new artifact with a new ID, retain `source_artifact_id`, and record both hashes in a trace event. Runtime code must never reinterpret an artifact in place.

## Evaluation

An evaluation task fixes the prompt, host/fixture, assertions, and budget. An evaluation result reports every assertion, exact usage, normalized score, and pass/fail. Release gates must run offline mock fixtures plus host-specific acceptance tests. Training promotion requires completed execution, passed verification, budget compliance, no unredacted secrets, and an unbroken trace hash chain.

## Canonical hashing

Hash inputs are UTF-8 JSON sorted by key with compact separators and no ASCII escaping. Hashes use lowercase SHA-256 prefixed by `sha256:`. Floating-point values in portable traces must be finite and use document units declared by the scene index.
