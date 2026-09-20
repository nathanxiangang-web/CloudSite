import pytest

from cloudsite import site_assets


@pytest.mark.parametrize(
    ("data", "extension"),
    [
        (b"\x89PNG\r\n\x1a\ncontent", "png"),
        (b"\xff\xd8\xffcontent", "jpg"),
        (b"RIFF\x04\x00\x00\x00WEBPcontent", "webp"),
    ],
)
def test_save_and_remove_share_image(monkeypatch, tmp_path, data, extension):
    monkeypatch.setattr(site_assets.settings, "data_dir", tmp_path)

    name = site_assets.save_share_image(data)
    path = site_assets.share_image_path(name)

    assert name.startswith("share-page-")
    assert name.endswith(f".{extension}")
    assert path is not None
    assert path.read_bytes() == data

    site_assets.remove_share_image(name)
    assert site_assets.share_image_path(name) is None


def test_share_image_rejects_invalid_content_and_unsafe_name(monkeypatch, tmp_path):
    monkeypatch.setattr(site_assets.settings, "data_dir", tmp_path)

    with pytest.raises(ValueError, match="PNG"):
        site_assets.save_share_image(b"not-an-image")

    assert site_assets.share_image_path("../share-page-test.png") is None
