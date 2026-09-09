from cloudsite.routers.home import _home_cache, invalidate_home_cache


def test_invalidate_home_cache_clears_cached_payload_and_timestamp():
    _home_cache["data"] = {"collections": [{"id": 3, "item_count": 0}]}
    _home_cache["fetched_at"] = 123.0

    invalidate_home_cache()

    assert _home_cache == {"data": None, "fetched_at": 0.0}
