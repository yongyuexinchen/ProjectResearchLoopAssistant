from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import SourceValidationError, validate_source_input
from app.db.models import Project, Source
from app.db.session import get_session
from app.research.profiles import research_profile_exists
from app.schemas.run import RunEnqueueRead
from app.schemas.workflow import ProjectSetupCreate, WorkflowRead
from app.services.audit import record_event
from app.services.workflow import enqueue_workflow, workflow_state

router = APIRouter(prefix="/projects", tags=["workflow"])


@router.post("/setup", response_model=RunEnqueueRead, status_code=status.HTTP_202_ACCEPTED)
def setup_project(payload: ProjectSetupCreate, session: Session = Depends(get_session)):
    if not research_profile_exists(payload.research_profile):
        raise HTTPException(status_code=400, detail="Research profile not found")
    try:
        validated = [validate_source_input(source.source_type, source.uri) for source in payload.sources]
    except SourceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    project = Project(**payload.model_dump(exclude={"sources"}))
    session.add(project)
    session.flush()
    for source, normalized in zip(payload.sources, validated, strict=True):
        session.add(Source(project_id=project.id, source_type=source.source_type, uri=source.uri,
                           normalized_uri=normalized.normalized_uri, metadata_json=normalized.metadata))
    session.flush()
    record_event(session, event_type="project.created", message="项目配置已保存，自动调研已排队",
                 project_id=project.id, payload={"source_count": len(validated)})
    run, job = enqueue_workflow(session, project)
    session.commit()
    return {"run": run, "job": job}


def require_project(session: Session, project_id: str):
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/{project_id}/workflow", response_model=RunEnqueueRead, status_code=status.HTTP_202_ACCEPTED)
def start_workflow(project_id: str, session: Session = Depends(get_session)):
    project = require_project(session, project_id)
    try:
        run, job = enqueue_workflow(session, project)
    except (SourceValidationError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    return {"run": run, "job": job}


@router.get("/{project_id}/workflow", response_model=WorkflowRead)
def get_workflow(project_id: str, run_id: str | None = None, session: Session = Depends(get_session)):
    project = require_project(session, project_id)
    try:
        return workflow_state(session, project, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
