from dataclasses import FrozenInstanceError

import pytest

from cloudsite.services.resource_name_parser import UNKNOWN, parse_resource_name


@pytest.mark.parametrize(
    ("name", "extension", "expected"),
    [
        ("CloudSite-v1.2.3-windows-x64.msi", "msi", ("windows", "x64", "1.2.3", "msi")),
        ("CloudSite_2.0.0_macos_arm64.dmg", ".dmg", ("macos", "arm64", "2.0.0", "dmg")),
        ("cloudsite-2026.09.10-linux-amd64.tar.gz", "gz", ("linux", "x64", "2026.09.10", "tar_gz")),
        ("client-3.4-android-armv7.apk", "apk", ("android", "arm", "3.4", "apk")),
        ("client-3.4-ios-arm64.ipa", "ipa", ("ios", "arm64", "3.4", "ipa")),
    ],
)
def test_known_platform_arch_version_and_package(name, extension, expected):
    result = parse_resource_name("r1", name, extension=extension)
    assert (result.platform, result.architecture, result.version, result.package_form) == expected
    assert set(("platform", "architecture", "version", "package_form")) <= result.evidence.keys()


def test_chinese_name_and_original_inputs_are_preserved():
    result = parse_resource_name(
        "resource-cn", "工具包-windows-x86-64-v1.0.zip", "/软件/工具包", ".zip", "application/zip"
    )
    assert result.language == "zh"
    assert result.architecture == "x64"
    assert result.original_name == "工具包-windows-x86-64-v1.0.zip"
    assert result.original_path == "/软件/工具包"
    assert result.evidence["language"].source == "name"


def test_unknown_and_misleading_substrings_do_not_guess():
    result = parse_resource_name("r2", "farmer-windmill-chaos-notes.txt")
    assert result.platform == UNKNOWN
    assert result.architecture == UNKNOWN
    assert result.language == UNKNOWN
    assert result.version == UNKNOWN
    assert result.package_form == UNKNOWN
    assert result.evidence == {}


def test_parser_is_deterministic_and_result_is_frozen():
    args = ("r3", "app-v9.8.7-linux-arm64.tar.xz", "/releases", "xz", "application/x-xz")
    first = parse_resource_name(*args)
    assert first == parse_resource_name(*args)
    with pytest.raises(FrozenInstanceError):
        first.platform = "windows"
