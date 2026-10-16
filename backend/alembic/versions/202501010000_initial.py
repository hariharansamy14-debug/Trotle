from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "202501010000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "roles" not in tables:
        op.create_table(
            "roles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=50), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
    if "permissions" not in tables:
        op.create_table(
            "permissions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=150), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("role_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=25), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email"),
        )
    if "data_sources" not in tables:
        op.create_table(
            "data_sources",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=150), nullable=False),
            sa.Column("source_type", sa.String(length=50), nullable=False),
            sa.Column("owner_id", sa.Integer(), nullable=False),
            sa.Column("connection_status", sa.String(length=50), nullable=True),
            sa.Column("configuration", sa.JSON(), nullable=True),
            sa.Column("encrypted_credentials_reference", sa.String(length=255), nullable=True),
            sa.Column("last_sync_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    op.drop_table("data_sources")
    op.drop_table("users")
    op.drop_table("permissions")
    op.drop_table("roles")
