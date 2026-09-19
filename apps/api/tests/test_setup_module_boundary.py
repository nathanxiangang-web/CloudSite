"""Regression coverage for the Setup workflow boundary."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.models import SetupWizardState as LegacySetupWizardState
from cloudsite.modules.setup.contracts.public import get_wizard_state
from cloudsite.modules.setup.infrastructure.models import (
    SetupWizardState as ModuleSetupWizardState,
)


async def test_setup_wizard_model_is_module_owned():
    assert LegacySetupWizardState is ModuleSetupWizardState


async def test_setup_wizard_state_projection_is_persistence_neutral():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)

    async with factory() as state:
        payload = await get_wizard_state(state)
        assert payload["current_step"] == "connect"
        assert payload["completed_steps"] == []
        assert payload["wizard_completed"] is False

        row = await state.get(ModuleSetupWizardState, 1)
        assert row is not None
        assert row.current_step == "connect"

    await engine.dispose()
