from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from app.models.models import Base


revision = "202610150000"
down_revision = "202501010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    inspector = inspect(bind)
    if "answers" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("answers")}
        if "evidence_coverage" not in columns:
            op.add_column("answers", sa.Column("evidence_coverage", sa.JSON(), nullable=True))
    if "conflicts" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("conflicts")}
        if "evidence" not in columns:
            op.add_column("conflicts", sa.Column("evidence", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "change_alerts" in tables:
        op.drop_table("change_alerts")
    for table, column in (("conflicts", "evidence"), ("answers", "evidence_coverage")):
        if table in tables and column in {item["name"] for item in inspect(bind).get_columns(table)}:
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_column(column)
