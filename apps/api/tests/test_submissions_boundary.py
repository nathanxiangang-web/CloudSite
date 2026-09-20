"""Users/Submissions ownership and public reference boundary regression."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.models import Submission as LegacySubmission
from cloudsite.models import User as LegacyUser
from cloudsite.modules.submissions.infrastructure.models import Submission
from cloudsite.modules.users.contracts.public import user_references
from cloudsite.modules.users.infrastructure.models import User
from cloudsite.platform.db import StateBase


def test_legacy_user_and_submission_exports_are_exact_module_classes():
    assert LegacyUser is User
    assert LegacySubmission is Submission
    assert User.__module__ == "cloudsite.modules.users.infrastructure.models"
    assert Submission.__module__ == (
        "cloudsite.modules.submissions.infrastructure.models"
    )


async def test_user_reference_contract_does_not_expose_credentials():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)

    async with factory() as state:
        user = User(
            username="reader",
            username_normalized="reader",
            password_hash="secret-hash",
            status="active",
        )
        state.add(user)
        await state.commit()
        user_id = user.id

    async with factory() as state:
        refs = await user_references(state, user_ids=[user_id])
        ref = refs[user_id]
        assert ref.username == "reader"
        assert ref.status == "active"
        assert not hasattr(ref, "password_hash")
        assert not hasattr(ref, "username_normalized")

    await engine.dispose()
