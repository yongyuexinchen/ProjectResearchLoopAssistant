from sqlalchemy import select

from app.db.models import LoopTurn, QualityScore
from app.engine import langgraph_runner
from tests.test_llm_report_generator import create_reportable_project, session_scope


def test_verify_node_reuses_score_for_same_input_key_without_duplicate_turn():
    with session_scope() as session:
        project, run, _ = create_reportable_project(session)
        state = {
            "project_id": project.id,
            "run_id": run.id,
            "context": {"snapshots": [], "codebase_maps": []},
            "persisted": {
                "evidence": [{"id": "evidence-1"}], "findings": [], "risks": [],
                "questions": [], "recommendations": [],
            },
        }
        token = langgraph_runner._GRAPH_SESSION.set(session)
        try:
            turns_before = len(list(session.scalars(select(LoopTurn).where(
                LoopTurn.run_id == run.id, LoopTurn.node_name == "verify_package"
            )).all()))
            first = langgraph_runner.verify_package_node(state)
            scores_after_first = len(list(session.scalars(
                select(QualityScore).where(QualityScore.run_id == run.id)
            ).all()))
            second = langgraph_runner.verify_package_node(state)
        finally:
            langgraph_runner._GRAPH_SESSION.reset(token)

        scores = list(session.scalars(select(QualityScore).where(QualityScore.run_id == run.id)).all())
        turns = list(session.scalars(select(LoopTurn).where(
            LoopTurn.run_id == run.id, LoopTurn.node_name == "verify_package"
        )).all())

        assert first["score"]["overall_score"] == second["score"]["overall_score"]
        assert len(scores) == scores_after_first
        assert len(turns) == turns_before + 1
