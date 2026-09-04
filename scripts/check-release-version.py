#!/usr/bin/env python3
"""CloudSite Release Version Consistency Gate.

检查所有版本引用一致：api __version__、web package.json、.env.example、
docker-compose 默认 tag、docker-compose.traefik.yml 默认 tag、README 离线示例，
可选 --tag v1.0.0 比对 Git Tag。不一致 exit 1。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def api_version():
    m = re.search(r"__version__\s*=\s*\"([^\"]+)\"", read("apps/api/cloudsite/__init__.py"))
    if not m:
        raise SystemExit("无法提取 apps/api/cloudsite/__init__.py __version__")
    return m.group(1)


def web_version():
    return json.loads(read("apps/web/package.json"))["version"]


def env_example_tag():
    m = re.search(r"^CLOUDSITE_IMAGE_TAG\s*=\s*v?(.+)$", read(".env.example"), re.M)
    if not m:
        raise SystemExit("无法提取 .env.example CLOUDSITE_IMAGE_TAG")
    return m.group(1).strip()


def compose_default_tag(fname):
    m = re.search(r"CLOUDSITE_IMAGE_TAG:-v([0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.]+)?)", read(fname))
    if not m:
        raise SystemExit("无法提取 " + fname + " 默认 CLOUDSITE_IMAGE_TAG")
    return m.group(1)


def readme_offline_version():
    m = re.search(r"cloudsite-api-v([0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.]+)?)-linux", read("README.md"))
    return m.group(1) if m else None


def main():
    expected_tag = None
    if "--tag" in sys.argv:
        i = sys.argv.index("--tag")
        if i + 1 < len(sys.argv):
            expected_tag = sys.argv[i + 1].lstrip("v")
    sources = {
        "api __version__": api_version(),
        "web package.json": web_version(),
        ".env.example CLOUDSITE_IMAGE_TAG": env_example_tag(),
        "docker-compose.yml default": compose_default_tag("docker-compose.yml"),
        "docker-compose.traefik.yml default": compose_default_tag("docker-compose.traefik.yml"),
    }
    rv = readme_offline_version()
    if rv:
        sources["README offline example"] = rv
    if expected_tag:
        sources["git tag"] = expected_tag
    print("版本引用：")
    for k, v in sources.items():
        print("  " + k + ": " + v)
    versions = set(sources.values())
    if len(versions) == 1:
        print("")
        print("OK 全部一致：" + versions.pop())
        return 0
    print("")
    print("FAIL 版本不一致：" + str(sorted(versions)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
