# CloudSite 1.0.0 Operations and Disaster Recovery

## Data responsibilities

- `data/state.db` contains the authoritative instance identity and business state. It cannot be regenerated from AList.
- `data/index.db` contains rebuildable folder, resource, search, and synchronization data.
- `data/office-cache/` contains disposable Office preview cache files.
- `.env` contains deployment settings and encryption keys and must be protected as sensitive data.

Never replace an established `state.db` with an empty file, never use the initial synchronization as a state recovery method, and never run `docker compose down -v` in production.

## Routine checks

```bash
docker compose ps
docker compose logs --tail=200 api web
curl -fsS http://127.0.0.1:3000/api/health
du -h data/state.db data/index.db
```

Review provider status, recent synchronization runs, pending folders, resource counts, operation-log growth, and backup results at regular intervals.

## Backup policy

```bash
bash scripts/backup.sh
bash scripts/verify-backup.sh cloudsite-backup-YYYYMMDD-HHMMSS.tar.gz
```

Keep at least one verified copy on another disk or host. Perform periodic restore drills into a temporary directory; the existence of an archive alone is not recovery evidence.

Backups contain encrypted AList credentials and key material and must use restricted access.

## Session and rate-limit maintenance

CloudSite periodically removes expired or long-revoked sessions and obsolete download-rate records. Active sessions are retained, and session activity writes are rate-limited to reduce database pressure.

Monitor operation-log growth and establish a retention policy appropriate to the deployment. Security and administration records normally deserve longer retention than routine runtime logs.

## AList outages

An AList outage must not destroy the existing index. Browse and search can continue from local data, while live storage metadata, preview, download, and synchronization return controlled errors.

When AList recovers, normal operations should resume without a CloudSite restart. If authentication fails, verify the account, password, base path, and encryption key before resaving credentials.

## Rolling synchronization safety

- A failed folder scan retains the previous index state.
- Missing objects require confirmation across two independent cycles.
- Suspicious large-scale additions or removals trigger scope-level zero-write protection.
- Progress is persistent and resumes from unfinished work after restart.
- Rate limits and access restrictions pause work through a circuit breaker instead of discarding the queue.

Do not manually clear synchronization state to bypass these protections.

## Recovery priorities

1. Preserve the current `.env` and `data/` directory before changing anything.
2. Determine whether the failure is configuration, `state.db`, `index.db`, AList, or networking.
3. Prefer a verified backup over manual database repair.
4. Restore into a temporary location first when time permits.
5. Validate users, credentials, counts, search, previews, downloads, shares, and synchronization after recovery.

See [Recovery guide](recovery-guide.md) for scenario-specific procedures.
