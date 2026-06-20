"""add owner_username to conversations

Revision ID: 0002_conversation_owner
Revises: 0001_initial
Create Date: 2026-06-20

This assumes no pre-existing conversations (a fresh learning DB), so the new NOT
NULL column gets a temporary server_default ('') purely so the ALTER succeeds. With
real data you would instead: add it nullable, backfill the owner for every row,
then ALTER to NOT NULL and add the foreign key.

`batch_alter_table` is what makes this run on SQLite, which can't ALTER columns in
place — Alembic recreates the table, copies the data, and swaps it in.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_conversation_owner"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.add_column(
            sa.Column("owner_username", sa.String(255), nullable=False, server_default="")
        )
        batch_op.create_index("ix_conversations_owner_username", ["owner_username"])
        batch_op.create_foreign_key(
            "fk_conversations_owner_username_users",
            "users",
            ["owner_username"],
            ["username"],
        )


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.drop_constraint("fk_conversations_owner_username_users", type_="foreignkey")
        batch_op.drop_index("ix_conversations_owner_username")
        batch_op.drop_column("owner_username")
