from cloudsite.platform.tasks import (
    Task, TaskStatus, TaskPriority, TaskRepository, TaskORM,
    Worker, TaskTypeRegistry, get_registry,
    RetryableError, PermanentError, RateLimitError,
    default_retry_policy, generate_lease_owner,
)
from cloudsite.migrations import CURRENT_SCHEMA_VERSION
from datetime import datetime, timezone

print(f"Schema version: {CURRENT_SCHEMA_VERSION}")
print(f"TaskStatus values: {[s.value for s in TaskStatus]}")
print(f"TaskPriority values: {[p.name for p in TaskPriority]}")

# Test state machine
t = Task(task_id="test_1", task_type="test.type")
print(f"Initial status: {t.status.value}")
t.lease("worker-1", expires_at=datetime.now(timezone.utc))
print(f"After lease: {t.status.value}")
t.start()
print(f"After start: {t.status.value}, attempt={t.attempt_count}")
t.succeed({"result": "ok"})
print(f"After succeed: {t.status.value}, terminal={t.is_terminal}")

# Test retry policy
rp = default_retry_policy
print(f"Retry delays: {[rp.get_delay(i) for i in range(1, 6)]}")

# Test invalid transition
try:
    t2 = Task(task_id="test_2", task_type="test.type")
    t2.succeed()
    print("ERROR: should have raised")
except Exception as e:
    print(f"Invalid transition correctly blocked: {e}")

# Test registry
reg = get_registry()
print(f"Registry count: {reg.count}")

print("All B2 imports and domain tests OK")