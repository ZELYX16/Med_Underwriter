import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.store.state_store import state_store


@pytest.fixture
def test_client():
    return TestClient(app)


@pytest.fixture
def sample_pdf_document():
    doc_id = "DOC_TEST_001"
    case_id = "CASE_DOC_TEST_001"
    applicant_id = "TEST_APP_001"

    # Ensure applicant exists
    if state_store.get_applicant(applicant_id) is None:
        state_store.create_applicant(
            applicant_id=applicant_id,
            applicant_profile={"name": "Test Applicant"},
        )

    # Ensure case exists
    if state_store.get_case(case_id) is None:
        state_store.create_case(
            case_id=case_id,
            applicant_id=applicant_id,
            state={"case_id": case_id, "applicant_id": applicant_id},
        )

    # Create a real test document under settings uploads directory
    uploads_dir = settings.synthetic_data_directory / "uploads" / applicant_id / case_id
    uploads_dir.mkdir(parents=True, exist_ok=True)
    test_pdf = uploads_dir / "DOC_TEST_001_report.pdf"
    test_content = b"%PDF-1.4 test document content for underwriting"
    test_pdf.write_bytes(test_content)

    # Add document record in state_store
    if state_store.get_case_document(doc_id) is None:
        state_store.add_case_document(
            document_id=doc_id,
            case_id=case_id,
            applicant_id=applicant_id,
            document_type="medical",
            filename="report.pdf",
            file_path=str(test_pdf),
            evidence_status="PROVIDED",
            metadata={"title": "Test Medical Report"},
        )

    yield {
        "document_id": doc_id,
        "case_id": case_id,
        "file_path": test_pdf,
        "content": test_content,
    }

    # Teardown
    if test_pdf.exists():
        test_pdf.unlink()


def test_document_content_streaming_success(test_client, sample_pdf_document):
    case_id = sample_pdf_document["case_id"]
    doc_id = sample_pdf_document["document_id"]

    response = test_client.get(f"/api/case/{case_id}/documents/{doc_id}/content")
    assert response.status_code == 200
    assert response.content == sample_pdf_document["content"]
    assert "application/pdf" in response.headers.get("content-type", "")
    assert "report.pdf" in response.headers.get("content-disposition", "")


def test_document_content_idor_cross_case_denied(test_client, sample_pdf_document):
    # Request document belonging to CASE_DOC_TEST_001 using different case_id CASE_OTHER
    wrong_case_id = "CASE_OTHER_999"
    doc_id = sample_pdf_document["document_id"]

    response = test_client.get(f"/api/case/{wrong_case_id}/documents/{doc_id}/content")
    assert response.status_code == 404
    data = response.json()
    error_msg = data.get("error", {}).get("message", "") or data.get("detail", "")
    assert "not found for this application" in error_msg.lower()


def test_document_content_traversal_blocked(test_client):
    # Create document record with path traversal payload
    bad_doc_id = "DOC_BAD_TRAVERSAL"
    case_id = "CASE_TRAVERSAL"
    app_id = "APP_TRAVERSAL"
    
    if state_store.get_applicant(app_id) is None:
        state_store.create_applicant(
            applicant_id=app_id,
            applicant_profile={"name": "Traversal Applicant"},
        )
    if state_store.get_case(case_id) is None:
        state_store.create_case(
            case_id=case_id,
            applicant_id=app_id,
            state={"case_id": case_id, "applicant_id": app_id},
        )

    # Target outside uploads directory
    traversal_path = str((settings.synthetic_data_directory / ".." / "traversal_target.txt").resolve())
    
    if state_store.get_case_document(bad_doc_id) is None:
        state_store.add_case_document(
            document_id=bad_doc_id,
            case_id=case_id,
            applicant_id=app_id,
            document_type="other",
            filename="traversal.txt",
            file_path=traversal_path,
        )

    response = test_client.get(f"/api/case/{case_id}/documents/{bad_doc_id}/content")
    assert response.status_code == 404
    data = response.json()
    error_msg = data.get("error", {}).get("message", "") or data.get("detail", "")
    assert "inaccessible" in error_msg.lower() or "missing" in error_msg.lower()


def test_document_content_missing_404(test_client):
    response = test_client.get("/api/case/CASE_NONEXISTENT/documents/DOC_NONEXISTENT/content")
    assert response.status_code == 404
