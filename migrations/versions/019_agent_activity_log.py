"""Add agent_activity_log for WS4 S6.

Revision ID: 019
Revises: 018
Create Date: 2026-04-23
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "019"
down_revision: str | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_activity_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("agent_id", sa.Text, nullable=False),
        sa.Column("session_id", sa.Text, nullable=True),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column(
            "event_data",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_activity_agent",
        "agent_activity_log",
        ["workspace_id", "agent_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_activity_type",
        "agent_activity_log",
        ["workspace_id", "event_type", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_activity_type", table_name="agent_activity_log")
    op.drop_index("ix_activity_agent", table_name="agent_activity_log")
    op.drop_table("agent_activity_log")
