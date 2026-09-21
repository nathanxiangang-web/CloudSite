"""手动同步与启动同步任务。

函数内部通过 ``cloudsite.main`` 引用可被测试 monkeypatch 的符号
（StateSession、get_system_values 等）。
"""
import asyncio
import random
from dataclasses import asdict


from ..config import settings
from ..modules.indexing.contracts.public import v2_sync_due
from ..modules.indexing.infrastructure.legacy_bridge import (
    run_indexing_v2_production as _run_indexing_v2_production,
)
from ..modules.indexing.infrastructure.production_store import ProductionIndexingStore
from ..modules.indexing.infrastructure.dirty_scope_repository import DirtyScopeRepository
from ..modules.indexing.infrastructure.rolling_verification import RollingVerificationService
from ..modules.indexing.infrastructure.verification_state_repository import (
    VerificationStateRepository,
)
from ..modules.resources.infrastructure.inventory_repository import (
    SqlAlchemyResourceInventoryRepository,
)
from ..modules.providers.contracts.public import enabled_provider_scan_sources
from ..modules.search.contracts.public import rebuild_public_search_index
from ..platform.db import index_session, state_session


def _production_indexing_store(session):
    resources = SqlAlchemyResourceInventoryRepository(session)
    return ProductionIndexingStore(resources)


async def run_indexing_v2_production():
    """Run indexing and refresh public search from the committed inventory."""
    result = await _run_indexing_v2_production(
        store_factory=_production_indexing_store,
    )
    if result.get("status") in {"success", "partial"}:
        async with state_session() as state, index_session() as index:
            rebuilt = await rebuild_public_search_index(state, index)
        result = {
            **result,
            "search_indexed": rebuilt.indexed,
        }
    return result


async def run_rolling_verification_once(*, batch_size: int = 20) -> dict:
    """Run one bounded rolling-verification pass without scheduling it.

    This is the production composition boundary used by E2E/manual validation.
    It intentionally does not alter sync scheduling; each root owns an
    independent State DB transaction.
    """
    async with state_session() as state:
        sources = await enabled_provider_scan_sources(state)

    summaries: list[dict] = []
    root_errors: list[str] = []

    for source in sources:
        for root in source.roots:
            async with state_session() as state:
                try:
                    summary = await RollingVerificationService(
                        batch_size=batch_size
                    ).verify_root(
                        provider=source.provider,
                        root=root,
                        verification_state=VerificationStateRepository(state),
                        dirty_scopes=DirtyScopeRepository(state),
                    )
                    await state.commit()
                    summaries.append(asdict(summary))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await state.rollback()
                    root_errors.append(
                        f"{root.storage_path}({root.content_type}): "
                        f"{type(exc).__name__}: {exc}"
                    )
                    summaries.append(
                        {
                            "root_mapping_id": root.root_mapping_id,
                            "status": "failed",
                            "selected": 0,
                            "checked": 0,
                            "unchanged": 0,
                            "dirty": 0,
                            "failed": 1,
                            "dirty_paths": [],
                            "failed_paths": [],
                            "errors": [root_errors[-1]],
                        }
                    )

    statuses = {item["status"] for item in summaries}
    if root_errors or "partial" in statuses or "failed" in statuses:
        status = "partial"
    elif summaries and statuses == {"baseline_required"}:
        status = "baseline_required"
    elif "baseline_required" in statuses:
        status = "partial"
    else:
        status = "success"

    return {
        "status": status,
        "roots": summaries,
        "errors": root_errors,
    }


async def _run_manual_sync_in_background(full: bool, force: bool) -> None:
    from cloudsite import main

    try:
        await run_indexing_v2_production()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await main.log_operation("sync", "failed", f"后台同步启动失败：{str(exc)[:1000]}", level="ERROR")
    finally:
        main.manual_sync_task = None


async def _safe_startup_sync():
    from cloudsite import main

    delay = random.uniform(
        settings.sync_startup_delay_min_seconds,
        settings.sync_startup_delay_max_seconds,
    )
    await asyncio.sleep(delay)
    async with main.StateSession() as session:
        values = await main.get_system_values(session)
        if not values["sync_on_startup"]:
            return
        if not await v2_sync_due(
            session,
            values["sync_interval_minutes"],
        ):
            return
    if main.manual_sync_task and not main.manual_sync_task.done():
        return
    main.manual_sync_task = asyncio.current_task()
    try:
        await run_indexing_v2_production()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await main.log_operation(
            "sync",
            "startup_sync_failed",
            f"启动同步失败：{type(exc).__name__}: {str(exc)[:900]}",
            level="ERROR",
        )
    finally:
        main.manual_sync_task = None
