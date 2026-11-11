import re
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.models import Project, ReportSnapshot
from app.db.session import get_session
from app.reports.diff import build_report_package_snapshot, diff_report_snapshots
from app.reports.pdf import render_markdown_pdf
from app.research.profiles import get_research_profile
from app.schemas.report import (
    ReportCreate,
    ReportDiffRead,
    ReportMarkdownRead,
    ReportReviewCreate,
    ReportSnapshotRead,
)
from app.services.reports import (
    create_intelligent_report_snapshot,
    create_report_snapshot,
    get_latest_report,
    review_report_snapshot,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["reports"])


@router.post("/reports", response_model=ReportSnapshotRead, status_code=status.HTTP_201_CREATED)
def create_report(
    project_id: str,
    payload: ReportCreate | None = Body(default=None),
    session: Session = Depends(get_session),
) -> ReportSnapshot:
    project = get_project_or_404(session, project_id)
    try:
        report = create_report_snapshot(session, project, run_id=payload.run_id if payload else None)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    session.refresh(report)
    return report


@router.post("/reports/intelligent", response_model=ReportSnapshotRead, status_code=status.HTTP_201_CREATED)
def create_intelligent_report(
    project_id: str,
    payload: ReportCreate | None = Body(default=None),
    session: Session = Depends(get_session),
) -> ReportSnapshot:
    project = get_project_or_404(session, project_id)
    try:
        report = create_intelligent_report_snapshot(session, project, run_id=payload.run_id if payload else None)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    session.refresh(report)
    return report


@router.get("/reports/latest", response_model=ReportSnapshotRead)
def get_latest_project_report(project_id: str, session: Session = Depends(get_session)) -> ReportSnapshot:
    project = get_project_or_404(session, project_id)
    report = get_latest_report(session, project)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/reports/{report_id}", response_model=ReportSnapshotRead)
def get_report(project_id: str, report_id: str, session: Session = Depends(get_session)) -> ReportSnapshot:
    return get_report_or_404(session, project_id, report_id)


@router.get("/reports/{report_id}/markdown", response_model=ReportMarkdownRead)
def get_report_markdown(project_id: str, report_id: str, session: Session = Depends(get_session)) -> dict[str, str]:
    report = get_report_or_404(session, project_id, report_id)
    return {"markdown": report.markdown_content}


@router.get("/reports/{report_id}/export.pdf")
def export_report_pdf(project_id: str, report_id: str, session: Session = Depends(get_session)) -> Response:
    project = get_project_or_404(session, project_id)
    report = get_report_or_404(session, project_id, report_id)
    pdf_content = render_markdown_pdf(title=report.title, markdown=report.markdown_content)
    filename = report_export_filename(project, report, ".pdf")
    return Response(
        content=pdf_content,
        media_type="application/pdf",
        headers={"Content-Disposition": attachment_disposition(filename, f"report-{report.id[:8]}.pdf")},
    )


@router.get("/reports/{report_id}/export.md")
def export_report_markdown(project_id: str, report_id: str, session: Session = Depends(get_session)) -> Response:
    project = get_project_or_404(session, project_id)
    report = get_report_or_404(session, project_id, report_id)
    filename = report_export_filename(project, report, ".md")
    return Response(
        content=report.markdown_content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": attachment_disposition(filename, f"report-{report.id[:8]}.md")},
    )


@router.get("/reports/{report_id}/diff", response_model=ReportDiffRead)
def get_report_diff(
    project_id: str,
    report_id: str,
    base_report_id: str,
    session: Session = Depends(get_session),
) -> dict:
    get_project_or_404(session, project_id)
    target_report = get_report_or_404(session, project_id, report_id)
    base_report = get_report_or_404(session, project_id, base_report_id)
    # 按报告创建时间截断 run 产物，避免评审反馈等后写入数据污染历史版本 diff。
    base_package = build_report_package_snapshot(session, base_report)
    target_package = build_report_package_snapshot(session, target_report)
    return {
        "base_report_id": base_report.id,
        "target_report_id": target_report.id,
        "diff": diff_report_snapshots(base_package, target_package),
    }


@router.post("/reports/{report_id}/review", response_model=ReportSnapshotRead)
def review_report(
    project_id: str,
    report_id: str,
    payload: ReportReviewCreate,
    session: Session = Depends(get_session),
) -> ReportSnapshot:
    project = get_project_or_404(session, project_id)
    report = get_report_or_404(session, project_id, report_id)
    try:
        review_report_snapshot(
            session,
            project,
            report,
            decision=payload.decision,
            comment=payload.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    session.refresh(report)
    return report


def report_export_filename(project: Project, report: ReportSnapshot, suffix: str) -> str:
    profile = get_research_profile(project.research_profile)
    created_at = report.created_at
    date_part = created_at.strftime("%Y%m%d") if created_at is not None else ""
    stem = f"{project.name}-{profile.label}-调研报告-{date_part}-{report.id[:8]}"
    safe_stem = re.sub(r'[\\/:*?"<>|\r\n]+', "-", stem)
    safe_stem = re.sub(r"\s+", " ", safe_stem).strip(" .-")
    if not safe_stem:
        safe_stem = f"report-{report.id[:8]}"
    return f"{safe_stem[:120]}{suffix}"


def attachment_disposition(filename: str, fallback: str) -> str:
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


def get_project_or_404(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def get_report_or_404(session: Session, project_id: str, report_id: str) -> ReportSnapshot:
    report = session.get(ReportSnapshot, report_id)
    if report is None or report.project_id != project_id:
        raise HTTPException(status_code=404, detail="Report not found")
    return report
