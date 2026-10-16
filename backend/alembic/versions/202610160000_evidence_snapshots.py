from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "202610160000"
down_revision = "202610150000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "change_alerts" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("change_alerts")}
        if "document_title" not in columns:
            op.add_column(
                "change_alerts",
                sa.Column("document_title", sa.String(length=255), nullable=False, server_default=""),
            )
        op.execute(sa.text(
            "UPDATE change_alerts SET document_title = "
            "(SELECT title FROM documents WHERE documents.id = change_alerts.document_id) "
            "WHERE document_title = '' AND document_id IS NOT NULL"
        ))

    inspector = inspect(bind)
    if "citations" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("citations")}
        for name, column in (
            ("source_id_snapshot", sa.Column("source_id_snapshot", sa.Integer(), nullable=True)),
            ("document_title_snapshot", sa.Column("document_title_snapshot", sa.String(length=255), nullable=True)),
            ("document_version_snapshot", sa.Column("document_version_snapshot", sa.String(length=50), nullable=True)),
        ):
            if name not in columns:
                op.add_column("citations", column)
        op.execute(sa.text(
            "UPDATE citations SET "
            "source_id_snapshot = (SELECT source_id FROM documents WHERE documents.id = citations.document_id), "
            "document_title_snapshot = (SELECT title FROM documents WHERE documents.id = citations.document_id), "
            "document_version_snapshot = (SELECT version FROM documents WHERE documents.id = citations.document_id) "
            "WHERE document_id IS NOT NULL"
        ))


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "citations" in tables:
        columns = {item["name"] for item in inspect(bind).get_columns("citations")}
        snapshot_columns = {"source_id_snapshot", "document_title_snapshot", "document_version_snapshot"} & columns
        if snapshot_columns:
            with op.batch_alter_table("citations") as batch_op:
                for column in snapshot_columns:
                    batch_op.drop_column(column)
    if "change_alerts" in tables:
        columns = {item["name"] for item in inspect(bind).get_columns("change_alerts")}
        if "document_title" in columns:
            with op.batch_alter_table("change_alerts") as batch_op:
                batch_op.drop_column("document_title")
