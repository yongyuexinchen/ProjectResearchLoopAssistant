from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ArchitectureDiagramRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    diagram_type: str
    title: str
    basis: str
    mermaid_source: str
    graph_json: dict[str, Any]
    stats_json: dict[str, Any]
    created_at: datetime
