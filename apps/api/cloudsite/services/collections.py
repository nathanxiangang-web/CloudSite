"""Backward-compatible Collections projection shim."""

from ..modules.collections.contracts.public import collection_view


async def collection_dict(state, index, row, include_items: bool = False) -> dict:
    return await collection_view(
        state,
        index,
        row,
        include_items=include_items,
    )


__all__ = ["collection_dict"]
