"""Run-scoped source inventory queries.

New collection rows carry the exact run id. Rows created before this column
existed are kept usable as a legacy fallback, but only up to that run's finish
time; a later run's rows can never leak into an older report.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnalysisRun, utc_now


def scoped_collection_rows(session: Session, model: Any, project_id: str, run_id: str | None):
    statement = select(model).where(model.project_id == project_id)
    if not run_id:
        return list(session.scalars(statement.order_by(model.created_at.asc(), model.id.asc())).all())

    scoped = list(session.scalars(
        statement.where(model.run_id == run_id).order_by(model.created_at.asc(), model.id.asc())
    ).all())
    if scoped:
        return scoped

    # Legacy rows have run_id=None. Use the run finish time when available;
    # rows created during/after an old run are still visible for migration
    # compatibility, while every new collection row carries an exact run id.
    run = session.get(AnalysisRun, run_id)
    cutoff = (run.completed_at or utc_now()) if run is not None else utc_now()
    legacy = statement.where(model.run_id.is_(None), model.created_at <= cutoff)
    return list(session.scalars(legacy.order_by(model.created_at.asc(), model.id.asc())).all())
