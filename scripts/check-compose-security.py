#!/usr/bin/env python3
"""CloudSite Compose 首装安全回归检查。

校验：
1. docker-compose.yml 与 docker-compose.traefik.yml 的 API environment 显式传递
   CLOUDSITE_SETUP_TOKEN: ${CLOUDSITE_SETUP_TOKEN:-}
2. 两者 CLOUDSITE_SECRET_KEY 均为 fail-closed 必填写法
   (${CLOUDSITE_SECRET_KEY:?...})，不允许 fallback 默认值。
3. 开发占位密钥 cloudsite-development-key-change-me 只允许出现在
   docker-compose.dev.yml，不能出现在正式或 Traefik Compose。

成功 exit 0，失败 exit 1。仅依赖 Python 标准库。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV_KEY = "cloudsite-development-key-change-me"
PROD_COMPOSES = ["docker-compose.yml", "docker-compose.traefik.yml"]
DEV_COMPOSE = "docker-compose.dev.yml"


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def extract_api_environment(text: str) -> dict[str, str]:
    """从 Compose 文本里粗略提取 services.api.environment 的 KEY: VALUE 行。

    只支持本仓库当前使用的扁平 `KEY: VALUE` 写法，足够做静态安全断言。
    """
    env: dict[str, str] = {}
    in_api = False
    in_env = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("services:"):
            in_api = False
            in_env = False
            continue
        if re.match(r"^  api:\s*$", line):
            in_api = True
            in_env = False
            continue
        if in_api and re.match(r"^    environment:\s*$", line):
            in_env = True
            continue
        if in_env:
            if re.match(r"^    \S", line):
                in_env = False
                continue
            m = re.match(r"^      (CLOUDSITE_\w+):\s*(.+)$", line)
            if m:
                env[m.group(1)] = m.group(2).strip()
    return env


def fail(msg: str) -> int:
    print("FAIL " + msg)
    return 1


def main() -> int:
    errors = 0

    for name in PROD_COMPOSES:
        text = read(name)
        env = extract_api_environment(text)

        token = env.get("CLOUDSITE_SETUP_TOKEN")
        if token is None:
            errors += fail(name + " 缺少 CLOUDSITE_SETUP_TOKEN")
        elif token != "${CLOUDSITE_SETUP_TOKEN:-}":
            errors += fail(name + " CLOUDSITE_SETUP_TOKEN 应为 ${CLOUDSITE_SETUP_TOKEN:-}，实际: " + token)

        secret = env.get("CLOUDSITE_SECRET_KEY", "")
        if not secret.startswith('"${CLOUDSITE_SECRET_KEY:?'):
            errors += fail(name + " CLOUDSITE_SECRET_KEY 必须为 fail-closed ${CLOUDSITE_SECRET_KEY:?...}，实际: " + secret)
        if DEV_KEY in text:
            errors += fail(name + " 不应包含开发占位密钥 " + DEV_KEY)

    dev_text = read(DEV_COMPOSE)
    if DEV_KEY not in dev_text:
        errors += fail(DEV_COMPOSE + " 应包含开发占位密钥 " + DEV_KEY + " 作为本地开发默认值")

    if errors == 0:
        print("OK 正式/Traefik Compose 显式传递 CLOUDSITE_SETUP_TOKEN、SECRET_KEY fail-closed、开发默认密钥仅出现在 " + DEV_COMPOSE)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
