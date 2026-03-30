"""Add user_platform_mappings table for channel identity resolution.

Revision ID: 010
Revises: 009
Create Date: 2026-03-27
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop old table if it exists with wrong schema (missing workspace_id, created_at).
    # Safe: table only contains auto-created mappings that will be re-created on next message.
    conn = op.get_bind()
    if conn.dialect.has_table(conn, "user_platform_mappings"):
        op.drop_table("user_platform_mappings")

    op.create_table(
        "user_platform_mappings",
        sa.Column("channel", sa.Text, nullable=False),
        sa.Column("channel_user_id", sa.Text, nullable=False),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column(
            "user_id",
            sa.Text,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint(
            "channel",
            "channel_user_id",
            "workspace_id",
            name="pk_user_platform_mapping",
        ),
    )
    op.create_index(
        "ix_upm_user_id",
        "user_platform_mappings",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_table("user_platform_mappings")
