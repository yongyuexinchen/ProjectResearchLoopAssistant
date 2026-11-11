from pydantic import Field
from pydantic import BaseModel

from app.schemas.project import ProjectCreate, SourceCreate
from app.schemas.report import ReportSnapshotRead
from app.schemas.run import AnalysisRunRead


class ProjectSetupCreate(ProjectCreate):
    sources: list[SourceCreate] = Field(min_length=1, max_length=50)


class WorkflowStageRead(BaseModel):
    key: str
    label: str
    status: str
    detail: str


class WorkflowRead(BaseModel):
    project_id: str
    run: AnalysisRunRead | None
    stages: list[WorkflowStageRead]
    progress: int
    status: str
    error: str | None
    report: ReportSnapshotRead | None
    architecture_count: int
    warnings: list[str]
