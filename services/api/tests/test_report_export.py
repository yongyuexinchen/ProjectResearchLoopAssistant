from urllib.parse import unquote

from tests.test_reports_api import create_project_with_run


def test_report_pdf_export_returns_pdf_bytes(tmp_path):
    client, project, _ = create_project_with_run(tmp_path)
    report = client.post(f"/projects/{project['id']}/reports").json()

    response = client.get(f"/projects/{project['id']}/reports/{report['id']}/export.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_export_filename_is_bound_to_project_and_profile(tmp_path):
    client, project, _ = create_project_with_run(tmp_path)
    report = client.post(f"/projects/{project['id']}/reports").json()

    markdown_response = client.get(f"/projects/{project['id']}/reports/{report['id']}/export.md")
    pdf_response = client.get(f"/projects/{project['id']}/reports/{report['id']}/export.pdf")

    markdown_disposition = unquote(markdown_response.headers["content-disposition"])
    pdf_disposition = unquote(pdf_response.headers["content-disposition"])

    assert "filename*=UTF-8''" in markdown_response.headers["content-disposition"]
    assert project["name"] in markdown_disposition
    assert "快速接手" in markdown_disposition
    assert "调研报告" in markdown_disposition
    assert markdown_disposition.rstrip('"').endswith(".md")
    assert project["name"] in pdf_disposition
    assert pdf_disposition.rstrip('"').endswith(".pdf")
