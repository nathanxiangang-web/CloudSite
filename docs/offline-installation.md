# CloudSite 1.0.0 Offline Installation

Use this procedure when the target server cannot access GitHub Container Registry but already has Docker Engine and the Docker Compose plugin.

## Select the architecture

Run `uname -m` on the target server:

- `x86_64`: use `amd64` assets.
- `aarch64` or `arm64`: use `arm64` assets.

## Download the 1.0.0 assets

Download the matching files from the [v1.0.0 release](https://github.com/nathanxiangang-web/CloudSite/releases/tag/v1.0.0):

- `cloudsite-api-v1.0.0-linux-amd64.tar.gz`
- `cloudsite-api-v1.0.0-linux-arm64.tar.gz`
- `cloudsite-web-v1.0.0-linux-amd64.tar.gz`
- `cloudsite-web-v1.0.0-linux-arm64.tar.gz`
- `cloudsite-v1.0.0-offline-deploy.zip`
- `SHA256SUMS.txt`

Do not mix assets from different releases.

## Verify checksums

On Linux:

```bash
sha256sum -c SHA256SUMS.txt
```

On Windows PowerShell, compare each result with `SHA256SUMS.txt`:

```powershell
Get-FileHash .\cloudsite-api-v1.0.0-linux-amd64.tar.gz -Algorithm SHA256
Get-FileHash .\cloudsite-web-v1.0.0-linux-amd64.tar.gz -Algorithm SHA256
Get-FileHash .\cloudsite-v1.0.0-offline-deploy.zip -Algorithm SHA256
```

Do not import an asset that fails verification.

## Import the images

```bash
arch=amd64 # use arm64 on an ARM server
gzip -dc "cloudsite-api-v1.0.0-linux-${arch}.tar.gz" | docker load
gzip -dc "cloudsite-web-v1.0.0-linux-${arch}.tar.gz" | docker load

docker image inspect ghcr.io/nathanxiangang-web/cloudsite-api:v1.0.0 \
  --format '{{.Os}}/{{.Architecture}} {{.Id}}'
docker image inspect ghcr.io/nathanxiangang-web/cloudsite-web:v1.0.0 \
  --format '{{.Os}}/{{.Architecture}} {{.Id}}'
```

Both images must report the selected Linux architecture.

## Configure and start

```bash
unzip cloudsite-v1.0.0-offline-deploy.zip
cd CloudSite
cp .env.example .env
```

Set a strong `CLOUDSITE_SECRET_KEY`, a one-time `CLOUDSITE_SETUP_TOKEN`, and keep `CLOUDSITE_IMAGE_TAG=v1.0.0`.

Start with both Compose files. The offline override sets `pull_policy: never` so Docker does not contact GHCR:

```bash
docker compose -f docker-compose.yml -f docker-compose.offline.yml config --images
docker compose -f docker-compose.yml -f docker-compose.offline.yml up -d --wait
docker compose -f docker-compose.yml -f docker-compose.offline.yml ps
curl -fsS http://127.0.0.1:3000/api/health
```

The health response must report `healthy` and version `1.0.0`.

## Verify the offline installation

After starting the stack, confirm the deployment layout before accepting it:

1. The extracted `CloudSite/` directory must contain `docker-compose.yml`, `docker-compose.offline.yml`, `.env.example`, `scripts/`, and `docs/`.
2. Both imported images must match the target architecture (reported by `docker image inspect` in the Import step).
3. `docker compose -f docker-compose.yml -f docker-compose.offline.yml config --images` must list `cloudsite-api:v1.0.0` and `cloudsite-web:v1.0.0` with `pull_policy: never`.
4. `docker compose -f docker-compose.yml -f docker-compose.offline.yml ps` must show both services healthy.
5. `curl -fsS http://127.0.0.1:3000/api/health` must return JSON with `"status":"healthy"` and `"version":"1.0.0"`.

Do not run `docker build` during an offline installation; the release images are pre-built and imported as tarballs.

## Offline backup and rollback

Create and verify a backup before replacing images:

```bash
bash scripts/backup.sh
bash scripts/verify-backup.sh cloudsite-backup-YYYYMMDD-HHMMSS.tar.gz
```

Keep the previous fixed images. To roll back, restore the previous tag in `.env` and run the same offline Compose command. Restore the verified pre-upgrade backup only when persistent data must also be rolled back.

## Safety rules

- Never upload `.env`, `data/`, databases, credentials, or production logs to a release.
- Never run `docker compose down -v` against an instance with data.
- Keep encryption keys stable after saving AList credentials.
- Verify the target architecture and checksums before importing images.
