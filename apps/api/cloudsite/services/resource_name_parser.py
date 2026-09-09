"""Pure deterministic resource-name parser for CloudSite A1.

Analyzes resource name, path, extension, and MIME type metadata and returns
evidence-backed suggestions for platform, architecture, language, version,
and package form. The parser is pure: it does not mutate its input or any
application state, performs no I/O, and produces identical output for
identical input plus parser version.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "PARSER_VERSION",
    "UNKNOWN",
    "Evidence",
    "ParseResult",
    "parse_resource_name",
]

PARSER_VERSION = "1.0.0"
UNKNOWN = "unknown"

# ---------------------------------------------------------------------------
# Token-based field maps.  Each key is matched against a *whole* token so
# that substrings inside unrelated words never trigger a match (e.g. "arm"
# inside "farmer", "win" inside "windmill", "ios" inside "chaos").
# ---------------------------------------------------------------------------

_PLATFORM_TOKENS: dict[str, str] = {
    "win": "windows",
    "windows": "windows",
    "win32": "windows",
    "win64": "windows",
    "mac": "macos",
    "macos": "macos",
    "osx": "macos",
    "darwin": "macos",
    "linux": "linux",
    "linux64": "linux",
    "linux32": "linux",
    "ubuntu": "linux",
    "debian": "linux",
    "centos": "linux",
    "fedora": "linux",
    "alpine": "linux",
    "android": "android",
    "ios": "ios",
    "iphone": "ios",
    "ipad": "ios",
    "iphoneos": "ios",
}

_ARCH_TOKENS: dict[str, str] = {
    "x64": "x64",
    "amd64": "x64",
    "x86_64": "x64",
    "x86": "x86",
    "i386": "x86",
    "i686": "x86",
    "ia32": "x86",
    "arm64": "arm64",
    "aarch64": "arm64",
    "arm": "arm",
    "armv7": "arm",
    "armv6": "arm",
    "armv5": "arm",
    "armhf": "arm",
    "armel": "arm",
    "armv7l": "arm",
    "armv6l": "arm",
}

_LANGUAGE_TOKENS: dict[str, str] = {
    "zh": "zh",
    "chinese": "zh",
    "cn": "zh",
    "en": "en",
    "english": "en",
    "eng": "en",
}

_EXTENSION_TO_PACKAGE: dict[str, str] = {
    "zip": "zip",
    "tar": "tar",
    "tgz": "tar_gz",
    "gz": "gz",
    "7z": "7z",
    "rar": "rar",
    "iso": "iso",
    "dmg": "dmg",
    "exe": "exe",
    "msi": "msi",
    "deb": "deb",
    "rpm": "rpm",
    "apk": "apk",
    "ipa": "ipa",
    "pkg": "pkg",
    "tbz2": "tar_bz2",
    "bz2": "bz2",
    "txz": "tar_xz",
    "xz": "xz",
}

_MIME_TO_PACKAGE: dict[str, str] = {
    "application/zip": "zip",
    "application/x-tar": "tar",
    "application/gzip": "gz",
    "application/x-gzip": "gz",
    "application/x-7z-compressed": "7z",
    "application/vnd.rar": "rar",
    "application/x-rar-compressed": "rar",
    "application/x-iso9660-image": "iso",
    "application/x-apple-diskimage": "dmg",
    "application/x-msdownload": "exe",
    "application/x-msi": "msi",
    "application/vnd.debian.binary-package": "deb",
    "application/x-rpm": "rpm",
    "application/vnd.android.package-archive": "apk",
    "application/x-itunes-ipa": "ipa",
    "application/x-newton-compatible-pkg": "pkg",
    "application/x-bzip2": "bz2",
    "application/x-xz": "xz",
}

_COMPOUND_SUFFIXES: tuple[tuple[str, str], ...] = (
    (".tar.gz", "tar_gz"),
    (".tar.bz2", "tar_bz2"),
    (".tar.xz", "tar_xz"),
)

# ---------------------------------------------------------------------------
# Regex patterns.
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
_DATE_VERSION_RE = re.compile(r"(?<![0-9.])((?:19|20)\d{2}\.\d{2}\.\d{2})(?![0-9])")
_SEMVER_RE = re.compile(r"(?<![0-9a-zA-Z])v?(\d+\.\d+\.\d+)(?![0-9])")
_MINOR_VERSION_RE = re.compile(r"(?<![0-9a-zA-Z.])v?(\d+\.\d+)(?![0-9.])")

_VERSION_PATTERNS: tuple[re.Pattern[str], ...] = (
    _DATE_VERSION_RE,
    _SEMVER_RE,
    _MINOR_VERSION_RE,
)

_X86_64_HYPHEN_RE = re.compile(r"(?<![a-zA-Z0-9])(x86-64)(?![a-zA-Z0-9])", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public data types.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Evidence:
    """Evidence fragment for a recognized field.

    Attributes:
        token:  The exact substring that was matched.
        source: Which input field the evidence came from
                ("name", "path", "extension", or "mime_type").
        index:  Character offset of *token* within the source string.
    """

    token: str
    source: str
    index: int = 0


@dataclass(frozen=True)
class ParseResult:
    """Typed, immutable parse result preserving the original input."""

    parser_version: str
    resource_id: str
    original_name: str
    original_path: str
    original_extension: str
    original_mime_type: str
    platform: str
    architecture: str
    language: str
    version: str
    package_form: str
    evidence: dict[str, Evidence]
