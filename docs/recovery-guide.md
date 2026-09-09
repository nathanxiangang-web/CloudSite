# CloudSite 1.0.0 Recovery Guide

Create a copy of the current `data/` directory and `.env` before any recovery attempt. Stop the affected services before replacing database files.

## `index.db` is missing or damaged

Expected behavior: CloudSite enters `INDEX_RECOVERY` instead of treating the instance as a new installation.

The recovery process preserves `state.db`, including users, settings, AList credentials, collections, shares, favorites, history, playback progress, and stable resource identities. Rebuild the content index through the supported recovery flow and verify `/api/health` when complete.

## `state.db` is missing or damaged

Expected behavior: CloudSite fails closed with `STATE_RECOVERY_REQUIRED`.

Restore a verified backup:

```bash
docker compose down
bash scripts/restore.sh cloudsite-backup-YYYYMMDD-HHMMSS.tar.gz --force
docker compose up -d --wait
curl -fsS http://127.0.0.1:3000/api/health
```

`state.db` cannot be reconstructed from AList. If no valid backup exists, the original instance identity and business data cannot be recovered.

## AList is unavailable

Indexed content can remain browsable while live downloads, previews, storage metadata, and synchronization fail with controlled errors. Restore the AList service or correct its credentials; the next operation should recover without restarting CloudSite.

If saved credentials cannot be decrypted, restore the matching `CLOUDSITE_MASTER_KEY` or `CLOUDSITE_SECRET_KEY`, or save the AList password again under the current key.

## Synchronization circuit breaker is open

Rate limits, access restrictions, WAF responses, or invalid upstream responses can pause the current rolling window. Unfinished folders remain pending. Correct the upstream condition and resume through the administration console after the cooldown.

Do not erase synchronization state to force progress.

## FTS recovery

An interrupted FTS update leaves a persistent dirty marker. On restart, CloudSite rebuilds FTS from the active folder and resource index without requesting AList, then clears the marker after a successful rebuild.

## Shares are unavailable

Check the share status, expiry, scope, access code, ticket, and download limit. Cancelled or expired shares are intentionally inaccessible even when their records remain visible for administrative retention.

## Database lock errors

1. Inspect long-running transactions and current synchronization work.
2. Allow active work to finish when possible.
3. Restart the API container only after confirming that no write operation should remain active.
4. Reduce synchronization pressure if lock errors recur.

## Verification after recovery

- `/api/health` reports `healthy` and version `1.0.0`.
- Existing users can sign in.
- The AList connection can be decrypted and tested.
- Resource, folder, collection, and share counts are plausible.
- Search, preview, download, and share flows work.
- Rolling synchronization state is not unexpectedly reset.
