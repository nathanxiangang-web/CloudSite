# ADR-002: Task Queue

Date: 2026-09-17
Status: Accepted
Supersedes: none

## Context

CloudSite needs background work: inventory scans, resource inspection, search
index rebuilds, AI suggestion generation, webhook delivery, and batch parser
evaluation. The legacy codebase has no unified task system; background work is
ad-hoc (threads, cron, inline). This causes:

- No visibility into running or failed jobs.
- No retry, lease, or deduplication; failed scans silently stall.
- No backpressure; a scan storm can starve request handlers.
- No resume after a worker restart; partial work is lost.

## Decision

Build a unified task queue in `platform/tasks/` with:

- A `tasks` table-backed queue (no external broker; SQLite/Postgres).
- Lease-based claiming: a worker claims a task with a TTL lease; if the worker
  dies, the lease expires and another worker re-claims.
- Retry with exponential backoff and a max retry count per task kind.
- Task kinds are registered with schemas; payloads are validated.
- Idempotency keys on tasks to prevent duplicate commits (e.g., snapshot IDs).
- Worker runtime in-process (not a separate process) for the monolith, with
  the option to run dedicated workers later.

Modules enqueue tasks via `platform/tasks` contracts; they never run background
work inline in request handlers.

## Alternatives Considered

1. **Celery + Redis** - rejected: adds two external dependencies and ops
   burden for a self-hosted single-binary deployment. Overkill at current scale.
2. **APScheduler** - rejected: no lease/dedup semantics; retry is primitive.
3. **Inline async / asyncio** - rejected: no durability; work is lost on
   restart; no backpressure or visibility.
4. **External broker (RabbitMQ, SQS)** - rejected for now; the DB-backed queue
   is sufficient and keeps the deployment single-binary. Can swap the queue
   implementation behind the same contract if scale demands it.

## Consequences

- Positive: unified visibility, retry, and backpressure for all background work.
- Positive: DB-backed queue needs no new infrastructure.
- Positive: lease + idempotency prevents duplicate commits on retry.
- Negative: DB-backed queue throughput is bounded by DB write capacity.
- Negative: in-process worker shares resources with request handlers; a
  runaway task can affect request latency. Mitigated by per-task timeouts and
  a separate worker mode for heavy jobs.
- Neutral: task payloads are JSON; large payloads must reference stored data.

## References

- platform/tasks/ (domain.py, worker.py, lease.py, retry.py, repository.py)
- ADR-003 (indexing strategy uses this task queue)