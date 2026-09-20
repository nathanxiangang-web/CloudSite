import pytest
from pydantic import ValidationError

from cloudsite.schemas import CollectionInput


def test_collection_cover_is_trimmed() -> None:
    payload = CollectionInput(name="Photography", cover="  r_123abc  ")
    assert payload.cover == "r_123abc"


@pytest.mark.parametrize("cover", ["/", "../image", "r_123/path", "中文封面"])
def test_collection_cover_rejects_path_like_values(cover: str) -> None:
    with pytest.raises(ValidationError):
        CollectionInput(name="Photography", cover=cover)
