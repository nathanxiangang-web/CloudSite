#!/usr/bin/env python3
"""CloudSite release version consistency gate.

Checks public/runtime version references stay aligned across the Python package,
API runtime, web package, Compose defaults, environment example and public docs.
Optionally compare them with a Git tag via ``--tag``.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def api_version():
    m = re.search(r'__version__\s*=\s*"([^"]+)"', read("apps/api/cloudsite/__init__.py"))
    if not m:
        raise SystemExit("cannot read apps/api/cloudsite/__init__.py __version__")
    return m.group(1)


def python_package_version():
    m = re.search(r'^version\s*=\s*"([^"]+)"', read("apps/api/pyproject.toml"), re.M)
    if not m:
        raise SystemExit("cannot read apps/api/pyproject.toml project version")
    return m.group(1)


def web_version():
    return json.loads(read("apps/web/package.json"))["version"]


def env_example_tag():
    m = re.search(r"^CLOUDSITE_IMAGE_TAG\s*=\s*v?(.+)$", read(".env.example"), re.M)
    if not m:
        raise SystemExit("cannot read .env.example CLOUDSITE_IMAGE_TAG")
    return m.group(1).strip()


def compose_default_tag(fname):
    m = re.search(r"CLOUDSITE_IMAGE_TAG:-v([0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.]+)?)", read(fname))
    if not m:
        raise SystemExit("cannot read default CLOUDSITE_IMAGE_TAG from " + fname)
    return m.group(1)


def readme_offline_version():
    m = re.search(r"cloudsite-api-v([0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.]+)?)-linux", read("README.md"))
    return m.group(1) if m else None


def contracts_doc_tag():
    m = re.search(
        r"`CLOUDSITE_IMAGE_TAG`\s*\|\s*`v?([0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.]+)?)`",
        read("docs/contracts.md"),
    )
    if not m:
        raise SystemExit("cannot read docs/contracts.md CLOUDSITE_IMAGE_TAG")
    return m.group(1)


def normalized_version(value):
    if re.fullmatch(r"[0-9]+\.[0-9]+", value):
        return value + ".0"
    return value


def main():
    expected_tag = None
    if "--tag" in sys.argv:
        i = sys.argv.index("--tag")
        if i + 1 < len(sys.argv):
            expected_tag = sys.argv[i + 1].lstrip("v")

    sources = {
        "api __version__": api_version(),
        "api pyproject.toml": python_package_version(),
        "web package.json": web_version(),
        ".env.example CLOUDSITE_IMAGE_TAG": env_example_tag(),
        "docker-compose.yml default": compose_default_tag("docker-compose.yml"),
        "docker-compose.traefik.yml default": compose_default_tag("docker-compose.traefik.yml"),
        "docs/contracts.md CLOUDSITE_IMAGE_TAG": contracts_doc_tag(),
    }
    rv = readme_offline_version()
    if rv:
        sources["README offline example"] = rv
    if expected_tag:
        sources["git tag"] = expected_tag

    print("Version references:")
    for key, value in sources.items():
        print(f"  {key}: {value}")

    versions = {normalized_version(version) for version in sources.values()}
    if len(versions) == 1:
        print("\nOK all version references match: " + versions.pop())
        return 0

    print("\nFAIL version mismatch: " + str(sorted(versions)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
