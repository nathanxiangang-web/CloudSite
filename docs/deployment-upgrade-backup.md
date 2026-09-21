# CloudSite 1.0.0 Deployment, Upgrade, and Backup

## Clean deployment

```bash
git clone https://github.com/nathanxiangang-web/CloudSite.git
cd CloudSite
cp .env.example .env
```

Set a strong `CLOUDSITE_SECRET_KEY`, a one-time `CLOUDSITE_SETUP_TOKEN`, and the fixed image tag:

```dotenv
CLOUDSITE_IMAGE_TAG=v1.0.0
```

Then validate and start the deployment:

```bash
docker compose config --quiet
docker compose up -d --wait
docker compose ps
curl -fsS http://127.0.0.1:3000/api/health
```

Complete the AList connection, initial synchronization, search, preview, download, share, and collection checks before treating the deployment as accepted.

## Indexing V2 Durable Scan rollout

Durable Scan is feature-gated and remains disabled by default. Do not enable it in production only because the containers are healthy; first pass the deployment resume E2E against a real provider-backed test root.

Set the flag in the test deployment:

```dotenv
CLOUDSITE_DURABLE_SCAN_ENABLED=true
```

Restart the API and verify the flag is actually present inside the container:

```bash
docker compose up -d --wait api
docker compose exec -T api sh -lc 'test "$CLOUDSITE_DURABLE_SCAN_ENABLED" = "true"'
```

Then run the destructive deployment E2E only on the dedicated test environment:

```bash
CLOUDSITE_E2E_ALLOW_RESTART=1 \
CLOUDSITE_E2E_COMPOSE_FILE=docker-compose.dev.yml \
bash scripts/e2e-durable-resume.sh
```

The gate intentionally restarts the API container. It refuses to start if another durable scan is already running, verifies the durable staging schema, requires an actually unfinished scan to be caught, resumes the same scan run after restart, requires zero pending/running/failed directories, and compares the final production inventory fingerprint with a clean-scan baseline.

A PASS from the browser smoke suite is not a substitute for this test: the browser E2E seed writes CloudSite-owned local data and does not exercise a real provider scan/checkpoint/resume path.

Keep `CLOUDSITE_DURABLE_SCAN_ENABLED=false` for normal deployment until this gate passes on the target deployment topology. If the E2E fails, leave the flag off and preserve `state.db` / `index.db` for diagnosis; do not delete scan rows or run `docker compose down -v` to make the test pass.

## Backup

```bash
bash scripts/backup.sh
bash scripts/verify-backup.sh cloudsite-backup-YYYYMMDD-HHMMSS.tar.gz
```

When the API is running, the backup script uses SQLite online backup for committed WAL data. The archive includes the databases, `.env`, and site assets, uses restrictive permissions, and must be treated as sensitive because it contains encrypted credentials and their key material.

Copy verified backups to another disk or host.

## Non-destructive restore drill

Restore into a temporary directory instead of overwriting the active deployment:

```bash
target="$(mktemp -d)"
bash scripts/restore.sh cloudsite-backup-YYYYMMDD-HHMMSS.tar.gz --target "$target"
find "$target" -maxdepth 2 -type f -print
```

Confirm that `.env`, `data/state.db`, and `data/index.db` are present and that the verification report passed.

## Upgrade within the 1.0 line

Record the current fixed tag and create a verified backup before changing images:

```bash
old_tag="$(sed -n 's/^CLOUDSITE_IMAGE_TAG=//p' .env | tail -n 1)"
bash scripts/backup.sh
bash scripts/verify-backup.sh cloudsite-backup-YYYYMMDD-HHMMSS.tar.gz
docker compose pull
docker compose up -d --wait
docker compose ps
curl -fsS http://127.0.0.1:3000/api/health
```

After the containers are healthy, verify the reported version, AList connection, folder and resource counts, recent synchronization state, user login, search, preview, download, collections, and shares.

Container status alone is not acceptance evidence.

## Rollback

For an image-only rollback, restore the previous fixed tag in `.env`:

```bash
docker compose pull
docker compose up -d --wait
```

If the upgrade changed persistent data and a data rollback is required:

```bash
docker compose down
bash scripts/restore.sh cloudsite-backup-YYYYMMDD-HHMMSS.tar.gz --force
docker compose up -d --wait
```

The restore process retains a rollback copy so the restore itself can be reversed.

## Traefik deployment

Use the same backup and acceptance rules with the Traefik Compose file:

```bash
docker network inspect "$TRAEFIK_NETWORK"
docker compose -f docker-compose.traefik.yml config --quiet
docker compose -f docker-compose.traefik.yml up -d --wait
```

Never delete the production data directory or run `docker compose down -v` as part of an upgrade.
