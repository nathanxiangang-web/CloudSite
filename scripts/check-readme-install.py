#!/usr/bin/env python3
"""Check that the README one-click install matches shipped configuration."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def fail(message: str) -> int:
    print("FAIL " + message)
    return 1


def env_value(text: str, key: str) -> str | None:
    match = re.search(r"^" + re.escape(key) + r"\s*=\s*(.*)$", text, re.M)
    return match.group(1).strip() if match else None


def main() -> int:
    errors = 0
    readme = read("README.md")
    env_example = read(".env.example")
    compose = read("docker-compose.yml")

    env_port = env_value(env_example, "CLOUDSITE_WEB_PORT")
    match = re.search(r"CLOUDSITE_WEB_PORT:-([0-9]+)", compose)
    compose_port = match.group(1) if match else None
    if not env_port:
        errors += fail(".env.example missing CLOUDSITE_WEB_PORT")
    if not compose_port:
        errors += fail("docker-compose.yml missing CLOUDSITE_WEB_PORT default")
    if env_port and compose_port and env_port != compose_port:
        errors += fail(f"port mismatch: env={env_port} compose={compose_port}")
    if env_port and env_port not in readme:
        errors += fail(f"README missing port {env_port}")

    env_data = env_value(env_example, "CLOUDSITE_DATA_PATH")
    match = re.search(r"CLOUDSITE_DATA_PATH:-([^:}]+)", compose)
    compose_data = match.group(1).strip() if match else None
    if not env_data:
        errors += fail(".env.example missing CLOUDSITE_DATA_PATH")
    if not compose_data:
        errors += fail("docker-compose.yml missing CLOUDSITE_DATA_PATH default")
    if env_data and compose_data and env_data != compose_data:
        errors += fail(f"data path mismatch: env={env_data} compose={compose_data}")
    if env_data and env_data not in readme:
        errors += fail(f"README missing data path {env_data}")

    if "CLOUDSITE_SECRET_KEY" not in readme:
        errors += fail("README missing CLOUDSITE_SECRET_KEY")
    if not re.search(r'CLOUDSITE_SECRET_KEY:\s*"\$\{CLOUDSITE_SECRET_KEY:\?', compose):
        errors += fail("Compose secret key is not fail-closed")

    if "/api/health" not in readme:
        errors += fail("README missing /api/health acceptance check")
    health_router = read("apps/api/cloudsite/routers/health.py")
    if '"/api/health"' not in health_router and "'/api/health'" not in health_router:
        errors += fail("health router does not declare /api/health")

    match = re.search(r"## 一键部署\n(.*?)(?=\n## |\Z)", readme, re.S)
    if not match:
        errors += fail("README missing one-click install section")
    elif "docker compose up -d --wait" not in match.group(1):
        errors += fail("one-click install does not use docker compose --wait")

    if "docs/installation.md" not in readme:
        errors += fail("README missing docs/installation.md link")
    if not (ROOT / "docs/installation.md").is_file():
        errors += fail("docs/installation.md does not exist")

    if errors == 0:
        print("OK README install instructions match environment, Compose, and health route")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
