"""run scoped source inventory

Revision ID: 20261111_0016
Revises: 20260712_0015
Create Date: 2026-11-11 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261111_0016"
down_revision: Union[str, Sequence[str], None] = "20260712_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("source_bundles", "source_snapshots", "codebase_maps"):
        op.add_column(table, sa.Column("run_id", sa.String(length=36), nullable=True))
        op.create_index(op.f(f"ix_{table}_run_id"), table, ["run_id"], unique=False)
        op.create_foreign_key(
            f"fk_{table}_run_id_analysis_runs",
            table,
            "analysis_runs",
            ["run_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table in ("source_bundles", "source_snapshots", "codebase_maps"):
        op.drop_constraint(f"fk_{table}_run_id_analysis_runs", table, type_="foreignkey")
        op.drop_index(op.f(f"ix_{table}_run_id"), table_name=table)
        op.drop_column(table, "run_id")
