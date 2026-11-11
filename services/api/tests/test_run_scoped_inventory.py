from app.context.builder import build_analysis_context
from app.db.models import AnalysisRun, CodebaseMap, Project, Source, SourceSnapshot
from app.services.reports import build_inventory, create_report_snapshot
from tests.test_llm_report_generator import create_reportable_project, session_scope


def test_inventory_and_context_use_exact_run_collection_rows():
    with session_scope() as session:
        project = Project(name="scoped", topic="scoped", analysis_goal="scope")
        session.add(project)
        session.flush()
        source = Source(project_id=project.id, source_type="local_directory", uri="repo",
                        normalized_uri="repo", status="collected")
        session.add(source)
        run_a = AnalysisRun(project_id=project.id, status="ready_for_review", max_turns=6)
        run_b = AnalysisRun(project_id=project.id, status="ready_for_review", max_turns=6)
        session.add_all([run_a, run_b])
        session.flush()
        session.add_all([
            SourceSnapshot(project_id=project.id, run_id=run_a.id, source_id=source.id,
                           source_type="local_directory", status="collected", title="A"),
            SourceSnapshot(project_id=project.id, run_id=run_b.id, source_id=source.id,
                           source_type="local_directory", status="collected", title="B"),
            CodebaseMap(project_id=project.id, run_id=run_a.id, source_id=source.id, root_label="A",
                        tech_stack_json=["python"], dependency_files_json=[], config_files_json=[],
                        test_files_json=[], entrypoint_files_json=[], file_tree_json=["old.py"],
                        skipped_items_json=[], metadata_json={}),
            CodebaseMap(project_id=project.id, run_id=run_b.id, source_id=source.id, root_label="B",
                        tech_stack_json=["python"], dependency_files_json=[], config_files_json=[],
                        test_files_json=[], entrypoint_files_json=[], file_tree_json=["new.py"],
                        skipped_items_json=[], metadata_json={}),
        ])
        session.flush()

        inventory = build_inventory(session, project, run_id=run_a.id)
        context = build_analysis_context(session, project.id, run_id=run_a.id)

        assert [item.title for item in inventory["snapshots"]] == ["A"]
        assert [item.root_label for item in inventory["codebase_maps"]] == ["A"]
        assert [item["title"] for item in context["snapshots"]] == ["A"]
        assert [item["root_label"] for item in context["codebase_maps"]] == ["A"]


def test_report_snapshot_does_not_mix_a_later_run_collection():
    with session_scope() as session:
        project, run_a, _ = create_reportable_project(session)
        source = session.query(Source).filter(Source.project_id == project.id).one()
        run_b = AnalysisRun(project_id=project.id, status="ready_for_review", max_turns=6)
        session.add(run_b)
        session.flush()
        session.add_all([
            SourceSnapshot(project_id=project.id, run_id=run_a.id, source_id=source.id,
                           source_type="local_directory", status="collected", title="RUN_A_SNAPSHOT"),
            SourceSnapshot(project_id=project.id, run_id=run_b.id, source_id=source.id,
                           source_type="local_directory", status="collected", title="RUN_B_SNAPSHOT"),
            CodebaseMap(project_id=project.id, run_id=run_b.id, source_id=source.id, root_label="RUN_B_MAP",
                        tech_stack_json=["typescript"], dependency_files_json=[], config_files_json=[],
                        test_files_json=[], entrypoint_files_json=[], readme_excerpt="RUN_B_README",
                        file_tree_json=[{"path": "new.ts", "kind": "file"}], skipped_items_json=[], metadata_json={}),
        ])
        session.flush()

        report = create_report_snapshot(session, project, run_id=run_a.id)

        assert "RUN_A_SNAPSHOT" in report.markdown_content
        assert "RUN_B_SNAPSHOT" not in report.markdown_content
        assert "RUN_B_README" not in report.markdown_content
        assert "RUN_B_MAP" not in report.markdown_content
