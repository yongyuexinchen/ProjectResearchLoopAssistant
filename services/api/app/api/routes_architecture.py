from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.architecture.service import generate_architecture, list_diagrams, regenerate_diagram
from app.db.models import AnalysisRun, ArchitectureDiagram, Project
from app.db.session import get_session
from app.schemas.architecture import ArchitectureDiagramRead
from app.services.audit import record_event

router = APIRouter(prefix="/projects/{project_id}", tags=["architecture"])


@router.get("/architecture", response_model=list[ArchitectureDiagramRead])
def get_architecture(project_id: str, run_id: str | None = None, session: Session = Depends(get_session)):
    project = get_project_or_404(session, project_id)
    if run_id is not None:
        require_run(session, project, run_id)
    return list_diagrams(session, project, run_id=run_id)


@router.post("/architecture", response_model=list[ArchitectureDiagramRead], status_code=status.HTTP_201_CREATED)
def create_architecture(project_id: str, run_id: str | None = None, session: Session = Depends(get_session)):
    project = get_project_or_404(session, project_id)
    if run_id is not None:
        require_run(session, project, run_id)
        latest_run_id = session.scalar(select(AnalysisRun.id).where(AnalysisRun.project_id == project.id)
            .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc()).limit(1))
        if run_id != latest_run_id:
            raise HTTPException(status_code=409, detail="历史调研保留其已保存的架构图，请在当前调研中重新生成。")
    try:
        rows = generate_architecture(session, project, run_id=run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record_event(
        session,
        event_type="architecture.generated",
        message="架构图已生成",
        project_id=project.id,
        payload={"diagram_types": [row.diagram_type for row in rows]},
    )
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows


@router.post("/architecture/{diagram_id}/regenerate", response_model=ArchitectureDiagramRead)
def regenerate_architecture_diagram(project_id: str, diagram_id: str, session: Session = Depends(get_session)):
    project = get_project_or_404(session, project_id)
    diagram = session.scalar(select(ArchitectureDiagram).where(
        ArchitectureDiagram.id == diagram_id, ArchitectureDiagram.project_id == project.id,
    ))
    if diagram is None:
        raise HTTPException(status_code=404, detail="Architecture diagram not found")
    try:
        regenerate_diagram(diagram)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record_event(
        session, event_type="architecture.diagram_regenerated", message="单张架构图已重新生成",
        project_id=project.id, payload={"diagram_id": diagram.id, "diagram_type": diagram.diagram_type},
    )
    session.commit()
    session.refresh(diagram)
    return diagram


def get_project_or_404(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def require_run(session: Session, project: Project, run_id: str):
    run = session.get(AnalysisRun, run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
