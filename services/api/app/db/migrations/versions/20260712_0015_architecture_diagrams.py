"""architecture diagrams

Revision ID: 20260712_0015
Revises: 20260706_0014
Create Date: 2026-07-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

LONG_TEXT = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")


revision: str = "20260712_0015"
down_revision: Union[str, Sequence[str], None] = "20260706_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "architecture_diagrams",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("diagram_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("basis", sa.String(length=80), nullable=False),
        sa.Column("mermaid_source", LONG_TEXT, nullable=False),
        sa.Column("graph_json", sa.JSON(), nullable=False),
        sa.Column("stats_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_architecture_diagrams_project_id"), "architecture_diagrams", ["project_id"], unique=False)
    op.create_index(op.f("ix_architecture_diagrams_diagram_type"), "architecture_diagrams", ["diagram_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_architecture_diagrams_diagram_type"), table_name="architecture_diagrams")
    op.drop_index(op.f("ix_architecture_diagrams_project_id"), table_name="architecture_diagrams")
    op.drop_table("architecture_diagrams")
