from sqlalchemy import select

from app.db.models import AnalysisRun, EvidenceItem, Finding, Project, Question, Recommendation, Risk
from app.engine.runner import persist_analysis_artifacts

from tests.test_llm_report_generator import session_scope


def analysis_payload(title: str) -> dict:
    return {
        "evidence": [
            {
                "client_ref": "evidence:snapshot:1",
                "source_id": None,
                "title": title,
                "summary": "已采集资料。",
                "evidence_type": "source_snapshot",
                "confidence": 85,
                "metadata": {},
            }
        ],
        "findings": [
            {
                "title": "项目定位",
                "summary": "示例项目。",
                "category": "project_positioning",
                "impact_level": "medium",
                "confidence": 85,
                "evidence_refs": ["evidence:snapshot:1"],
                "metadata": {},
            }
        ],
        "risks": [
            {
                "title": "运行时未验证",
                "summary": "静态扫描。",
                "severity": "medium",
                "mitigation": "跑一次真实流程。",
                "evidence_refs": ["evidence:snapshot:1"],
                "metadata": {},
            }
        ],
        "questions": [
            {
                "prompt": "教学受众的基础如何？",
                "reason": "缺少受众信息。",
                "impact": "high",
                "status": "open",
                "metadata": {"source": "llm_analyzer", "section": "教学目标与受众"},
            }
        ],
        "recommendations": [
            {
                "summary": "先补课程材料。",
                "rationale": "当前只有文件级证据。",
                "confidence": 80,
                "next_steps": ["补材料"],
                "metadata": {},
            }
        ],
    }


def counts(session) -> dict[str, int]:
    return {
        "evidence": len(list(session.scalars(select(EvidenceItem)))),
        "findings": len(list(session.scalars(select(Finding)))),
        "risks": len(list(session.scalars(select(Risk)))),
        "questions": len(list(session.scalars(select(Question)))),
        "recommendations": len(list(session.scalars(select(Recommendation)))),
    }


def test_repeated_persist_replaces_artifacts_and_downgrades_llm_high_question():
    with session_scope() as session:
        project = Project(name="Resume project", topic="topic", analysis_goal="goal")
        session.add(project)
        session.flush()
        run = AnalysisRun(project_id=project.id, status="paused_for_input")
        session.add(run)
        session.flush()

        persist_analysis_artifacts(session, project, run, analysis_payload("第一次采集"))
        persist_analysis_artifacts(session, project, run, analysis_payload("第二次采集"))
        session.flush()

        assert counts(session) == {
            "evidence": 1,
            "findings": 1,
            "risks": 1,
            "questions": 1,
            "recommendations": 1,
        }
        question = session.scalar(select(Question))
        assert question.impact == "medium"
        assert question.metadata_json["original_impact"] == "high"
        assert question.metadata_json["advisory_downgrade"] is True
        evidence = session.scalar(select(EvidenceItem))
        assert evidence.title == "第二次采集"
