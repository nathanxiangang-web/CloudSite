import re

filepath = "apps/api/cloudsite/migrations.py"

with open(filepath, "r") as f:
    content = f.read()

migration_fn = '''
async def state_v28_to_v29_upgrade(conn: AsyncConnection) -> None:
    """Schema v28 -> v29: platform_tasks table for unified Task/Worker/Lease system."""
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS platform_tasks("
        "task_id VARCHAR(64) PRIMARY KEY,"
        "task_type VARCHAR(128) NOT NULL,"
        "queue VARCHAR(64) NOT NULL DEFAULT 'default',"
        "status VARCHAR(32) NOT NULL DEFAULT 'pending',"
        "priority INTEGER NOT NULL DEFAULT 5,"
        "payload JSON,"
        "dedupe_key VARCHAR(256),"
        "parent_task_id VARCHAR(64),"
        "root_task_id VARCHAR(64) NOT NULL,"
        "max_attempts INTEGER NOT NULL DEFAULT 5,"
        "attempt_count INTEGER NOT NULL DEFAULT 0,"
        "created_at DATETIME NOT NULL,"
        "scheduled_at DATETIME NOT NULL,"
        "started_at DATETIME,"
        "finished_at DATETIME,"
        "lease_owner VARCHAR(128),"
        "lease_expires_at DATETIME,"
        "retry_at DATETIME,"
        "last_error_code VARCHAR(128),"
        "last_error_message TEXT,"
        "result JSON)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_platform_tasks_task_type "
        "ON platform_tasks (task_type)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_platform_tasks_queue "
        "ON platform_tasks (queue)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_platform_tasks_status "
        "ON platform_tasks (status)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_platform_tasks_dedupe_key "
        "ON platform_tasks (dedupe_key)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_platform_tasks_retry_at "
        "ON platform_tasks (retry_at)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_platform_tasks_queue_status "
        "ON platform_tasks (queue, status)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_platform_tasks_status_retry "
        "ON platform_tasks (status, retry_at)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_platform_tasks_dedupe_status "
        "ON platform_tasks (dedupe_key, status)"
    )

'''

content = content.replace("STATE_MIGRATIONS: list", migration_fn + "STATE_MIGRATIONS: list")

old_entry = 'Migration(id="state_v27_to_v28", from_version=27, to_version=28, upgrade=state_v27_to_v28_upgrade),\n]'
new_entry = 'Migration(id="state_v27_to_v28", from_version=27, to_version=28, upgrade=state_v27_to_v28_upgrade),\n    Migration(id="state_v28_to_v29", from_version=28, to_version=29, upgrade=state_v28_to_v29_upgrade),\n]'

content = content.replace(old_entry, new_entry)

with open(filepath, "w") as f:
    f.write(content)

print("Migration v28_to_v29 added successfully")