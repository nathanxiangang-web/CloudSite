"""Setup-owned persistence models."""

from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ....platform.db import StateBase


class SetupWizardState(StateBase):
    """Singleton progress state for the first-run setup workflow."""

    __tablename__ = "setup_wizard_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    current_step: Mapped[str] = mapped_column(String(20), default="connect")
    completed_steps_json: Mapped[str] = mapped_column(Text, default="[]")
    connect_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    scope_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    preset_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    samples_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    brand_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    preview_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    publish_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    wizard_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    started_at: Mapped[str] = mapped_column(String(40), default="")
    completed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


__all__ = ["SetupWizardState"]
