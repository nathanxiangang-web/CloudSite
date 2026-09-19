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

_TOKEN_RE = re.compile(r"x86_64|[a-zA-Z0-9]+", re.IGNORECASE)
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


def _token_matches(value: str):
    for match in _TOKEN_RE.finditer(value):
        yield match.group(0), match.group(0).casefold(), match.start()


def _first_token_evidence(
    sources: tuple[tuple[str, str], ...],
    mapping: dict[str, str],
) -> tuple[str, Evidence] | None:
    for source, value in sources:
        for token, folded, index in _token_matches(value):
            mapped = mapping.get(folded)
            if mapped is not None:
                return mapped, Evidence(token=token, source=source, index=index)
    return None


def _architecture_evidence(
    sources: tuple[tuple[str, str], ...],
) -> tuple[str, Evidence] | None:
    for source, value in sources:
        special = _X86_64_HYPHEN_RE.search(value)
        if special is not None:
            return "x64", Evidence(
                token=special.group(0), source=source, index=special.start()
            )
        for token, folded, index in _token_matches(value):
            mapped = _ARCH_TOKENS.get(folded)
            if mapped is not None:
                return mapped, Evidence(token=token, source=source, index=index)
    return None


def _version_evidence(
    sources: tuple[tuple[str, str], ...],
) -> tuple[str, Evidence] | None:
    for pattern in _VERSION_PATTERNS:
        for source, value in sources:
            match = pattern.search(value)
            if match is not None:
                return match.group(1), Evidence(
                    token=match.group(0), source=source, index=match.start()
                )
    return None


def _package_evidence(
    name: str,
    extension: str,
    mime_type: str,
) -> tuple[str, Evidence] | None:
    folded_name = name.casefold()
    for suffix, package_form in _COMPOUND_SUFFIXES:
        if folded_name.endswith(suffix):
            return package_form, Evidence(
                token=name[-len(suffix) :],
                source="name",
                index=len(name) - len(suffix),
            )

    normalized_extension = extension.strip().lstrip(".").casefold()
    if normalized_extension in _EXTENSION_TO_PACKAGE:
        token_start = extension.casefold().rfind(normalized_extension)
        return _EXTENSION_TO_PACKAGE[normalized_extension], Evidence(
            token=extension[token_start:] if token_start >= 0 else extension,
            source="extension",
            index=max(token_start, 0),
        )

    suffix = name.rsplit(".", 1)[-1].casefold() if "." in name else ""
    if suffix in _EXTENSION_TO_PACKAGE:
        return _EXTENSION_TO_PACKAGE[suffix], Evidence(
            token=name[-len(suffix) :], source="name", index=len(name) - len(suffix)
        )

    normalized_mime = mime_type.strip().casefold()
    if normalized_mime in _MIME_TO_PACKAGE:
        return _MIME_TO_PACKAGE[normalized_mime], Evidence(
            token=mime_type, source="mime_type", index=0
        )
    return None


def parse_resource_name(
    resource_id: str,
    name: str,
    path: str = "",
    extension: str = "",
    mime_type: str = "",
) -> ParseResult:
    """Return conservative suggestions without mutating application state."""
    evidence: dict[str, Evidence] = {}
    text_sources = (("name", name), ("path", path))

    platform_match = _first_token_evidence(text_sources, _PLATFORM_TOKENS)
    architecture_match = _architecture_evidence(text_sources)
    language_match = _first_token_evidence(text_sources, _LANGUAGE_TOKENS)
    if language_match is None:
        for source, value in text_sources:
            cjk = _CJK_RE.search(value)
            if cjk is not None:
                language_match = (
                    "zh",
                    Evidence(token=cjk.group(0), source=source, index=cjk.start()),
                )
                break
    version_match = _version_evidence(text_sources)
    package_match = _package_evidence(name, extension, mime_type)

    matches = {
        "platform": platform_match,
        "architecture": architecture_match,
        "language": language_match,
        "version": version_match,
        "package_form": package_match,
    }
    for field, match in matches.items():
        if match is not None:
            evidence[field] = match[1]

    return ParseResult(
        parser_version=PARSER_VERSION,
        resource_id=resource_id,
        original_name=name,
        original_path=path,
        original_extension=extension,
        original_mime_type=mime_type,
        platform=platform_match[0] if platform_match else UNKNOWN,
        architecture=architecture_match[0] if architecture_match else UNKNOWN,
        language=language_match[0] if language_match else UNKNOWN,
        version=version_match[0] if version_match else UNKNOWN,
        package_form=package_match[0] if package_match else UNKNOWN,
        evidence=evidence,
    )
