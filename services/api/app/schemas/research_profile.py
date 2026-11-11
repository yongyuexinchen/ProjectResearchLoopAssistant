from pydantic import BaseModel


class ReportSectionSpecRead(BaseModel):
    heading: str
    question: str


class ResearchProfileRead(BaseModel):
    key: str
    label: str
    description: str
    audience: str
    core_question: str
    checklist: list[str]
    quality_weights: dict[str, float]
    verifier_checks: list[str]
    report_sections: list[str]
    section_plan: list[ReportSectionSpecRead]
    required_evidence_types: list[str]
    focus_points: list[str]
    deliverable: str
    analysis_directives: list[str]
