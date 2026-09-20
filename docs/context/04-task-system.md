# AI Context Pack: Task System

Purpose: explain the task queue so an AI agent can add or modify background
work correctly. `platform/tasks` is the durable queue for work that has a guaranteed
worker consumer. Do not convert an existing synchronous compatibility path to
enqueue-only behavior unless deployment guarantees that consumer.

## Why a Task System

CloudSite needs background work for:
- Inventory scans and resource inspection (indexing).
- Search index rebuilds and recovery (search).
- AI suggestion generation and parser evaluation (automation).
- Webhook delivery with retry (notifications).
- Batch processing (automation).
- Cache warm-up (delivery).

The task system provides visibility, retry, lease, deduplication, and
backpressure that ad-hoc threads/cron cannot.

## Architecture

```text
platform/tasks/
  domain.py       - task entity, status, kinds
  repository.py   - DB-backed queue (tasks table)
  lease.py        - lease claiming and expiry
  retry.py        - exponential backoff, max retry per kind
  worker.py       - worker runtime (in-process or dedicated)
  registry.py     - task kind registration with handlers and schemas
  api.py          - enqueue/claim/complete/fail contracts
  models.py       - ORM models for the tasks table
  errors.py       - typed task errors
```

## Task Lifecycle

```text
enqueued -> claimed (lease acquired) -> running -> completed
                                      \-> failed (retry if retries left)
                                      \-> dead (max retries exceeded)
```

- A worker claims a task with a TTL lease. If the worker dies, the lease
  expires and another worker re-claims. No work is lost.
- On failure, retry with exponential backoff up to max retries for that kind.
- Idempotency keys prevent duplicate commits on retry (e.g., snapshot IDs).
- A dead task is surfaced for admin inspection; it is not silently dropped.

## Task Kinds

| Kind | Module | Purpose |
|------|--------|---------|
| scan_category | indexing | walk a content root category, emit skeletons |
| inspect_resource | indexing | fetch full detail for one resource |
| reconcile_snapshot | indexing | commit snapshot to DB atomically |
| rebuild_index | search | target task kind for full FTS rebuild; current admin compatibility endpoint is still synchronous |
| recover_index | search | target task kind for recovery; startup dirty recovery is currently synchronous |
| generate_suggestions | automation | AI/rule metadata suggestions |
| evaluate_parser | automation | score parser candidate against corpus |
| run_batch | automation | process a batch of candidates/suggestions |
| deliver_webhook | notifications | webhook delivery with retry |
| warm_cache | delivery | cache warm-up for hot resources |

## How to Add a Task Kind

1. Define the task payload schema in the module's public/ directory.
2. Register the kind in platform/tasks/registry.py with handler and max retries.
3. Enqueue via platform/tasks api: `enqueue(kind, payload, idempotency_key)`.
4. Implement the handler as an application service in the module.
5. Never run the work inline in a request handler; always enqueue.

## Rules

1. Request handlers enqueue tasks; they do not run the work inline.
2. Task payloads are JSON; large payloads must reference stored data, not
   embed it.
3. Handlers run with system scope, not a user session. The lease owner is a
   worker, not a user.
4. Handlers must be idempotent: a retry after a lease expiry must not double-
   commit. Use idempotency keys.
5. Per-task timeouts prevent a runaway task from starving the worker.
6. The current production worker runtime is a dedicated process (`python -m cloudsite.worker_main`).
   The base `docker-compose.yml` does not start it; `docker-compose.worker.yml` is an optional overlay.
   The FastAPI lifespan does not currently start an in-process `Worker`.

## Lease Semantics

- Claim: a worker acquires a lease with a TTL (e.g., 5 minutes).
- Heartbeat: for long tasks, the worker renews the lease before TTL.
- Expiry: if the lease expires (worker died), the task is re-queueable.
- No duplicate execution: a task is only claimed by one worker at a time.

## Retry Semantics

- Backoff: exponential (e.g., 2^n seconds) with jitter.
- Max retries: per task kind, registered in the registry.
- Dead tasks: after max retries, marked dead; surfaced for admin inspection.
- Retryable errors: transient (provider unavailable, DB locked).
- Non-retryable errors: validation failures; marked dead immediately.

## Backpressure

- The queue is DB-backed; enqueue is a DB write. Under load, enqueue slows,
  providing natural backpressure.
- Workers have a concurrency limit; they do not claim more than N tasks at
  once.
- A scan storm (many scan_category enqueues) does not starve request handlers
  because workers are bounded and request handling is separate.

## Observability

- Task state transitions are logged via platform/observability.
- Metrics: queue depth, claim latency, completion rate, dead task count.
- Admin endpoints expose queue status for operational inspection.