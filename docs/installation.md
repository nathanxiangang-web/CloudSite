# CloudSite 1.0.0 Installation Guide

CloudSite 1.0.0 supports online Docker deployment, an existing Traefik network, and offline installation on `linux/amd64` and `linux/arm64`.

## Requirements

- Docker Engine
- Docker Compose plugin
- An accessible AList instance
- A dedicated AList account with only the permissions CloudSite needs

Node.js and Python are not required on the deployment server.

## Standard Docker deployment

```bash
git clone https://github.com/nathanxiangang-web/CloudSite.git
cd CloudSite
cp .env.example .env
```

Edit `.env` before starting the service:

```dotenv
CLOUDSITE_SECRET_KEY=replace-with-a-long-random-secret
CLOUDSITE_MASTER_KEY=
CLOUDSITE_SETUP_TOKEN=replace-with-a-one-time-setup-token
CLOUDSITE_IMAGE_TAG=v1.0.0
```

Generate suitable values on any machine with Python. `CLOUDSITE_SECRET_KEY` must be at least 32 characters; `CLOUDSITE_SETUP_TOKEN` is a separate one-time value used only during first setup:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"  # CLOUDSITE_SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"  # CLOUDSITE_SETUP_TOKEN
```

Start and verify CloudSite:

```bash
docker compose config --quiet
docker compose up -d --wait
docker compose ps
curl -fsS http://127.0.0.1:3000/api/health
```

Open `http://SERVER_IP:3000`. The default Compose file exposes Web on port `3000`; API remains on the internal Compose network. Persistent data is stored under `${CLOUDSITE_DATA_PATH:-./data}`.

## Initial configuration

1. Open `/admin/setup` on the CloudSite Web address.
2. Enter the AList URL, AList administrator username/password, and the exact `CLOUDSITE_SETUP_TOKEN` from `.env`. Do not enter `CLOUDSITE_SECRET_KEY` in the setup-token field.
3. If initialization fails, the page reports the AList diagnostic code when available (for example `AL-002` for connectivity failures).
4. After setup succeeds, sign in at `/admin/login` with the AList administrator credentials.
5. Add one or more content roots and assign their content types.
6. Run the initial synchronization and wait for it to finish successfully.
7. Configure site identity, registration, collections, and sharing defaults.
8. Remove `CLOUDSITE_SETUP_TOKEN` from `.env` and restart the services.

Do not change `CLOUDSITE_SECRET_KEY` or `CLOUDSITE_MASTER_KEY` after AList credentials have been saved. The encrypted password cannot be recovered with a different key.

## Traefik HTTPS deployment

Set the external routing values in `.env`:

```dotenv
CLOUDSITE_DOMAIN=cloud.example.com
TRAEFIK_NETWORK=my-servers_app-net
TRAEFIK_ENTRYPOINT=websecure
TRAEFIK_CERT_RESOLVER=myresolver
```

Verify that the external Docker network exists, then start the Traefik variant:

```bash
docker network inspect "$TRAEFIK_NETWORK"
docker compose -f docker-compose.traefik.yml config --quiet
docker compose -f docker-compose.traefik.yml up -d --wait
```

The Traefik Compose file does not publish ports `3000` or `8000`. Traefik reaches Web through the configured external network.

## Offline installation

Use the release assets that match the target architecture. See [Offline installation](offline-installation.md) for checksum verification, image import, startup, and rollback instructions.

## Source development

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

Development mode exposes Web on `3000` and API on `8000`.

```bash
docker compose -f docker-compose.dev.yml down
```

Stopping the services does not remove the data directory.

## Upgrade and rollback

Always create and verify a backup before changing the fixed image tag. See [Deployment, upgrade, and backup](deployment-upgrade-backup.md) for the complete procedure.

Never run `docker compose down -v` on an instance that contains data.
