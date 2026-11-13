import pytest
import pymupdf
from pathlib import Path
from app.rag import structured as st
from app.services.review_gate import evaluate_review_gate

def test_document_completeness_gate_on_scanned_pdf(tmp_path):
    # Create an empty/scanned mock PDF with no vector text and no tables
    pdf_path = tmp_path / "scanned_doc.pdf"
    doc = pymupdf.open()
    doc.new_page() # empty page
    doc.save(str(pdf_path))
    doc.close()

    parsed = st.parse_pdf(pdf_path)
    assert parsed is not None
    assert parsed.get("document_defect") == "scanned_or_insufficient_text"
    assert parsed.get("sections") == []

    # Check that build_applicant_facts catches this as a defective document
    facts = st.build_applicant_facts([pdf_path])
    assert "scanned_doc.pdf" in facts["unparsed_files"]
    defects = facts.get("document_defects", [])
    assert any(d["file_name"] == "scanned_doc.pdf" and d["defect"] == "scanned_or_insufficient_text" for d in defects)

def test_review_gate_trips_on_document_defects():
    state = {
        "final_status": "agent1",
        "document_defects": [{"file_name": "scan_report.pdf", "defect": "scanned_or_insufficient_text"}],
        "medical_risk_score": 10.0,
        "overall_risk_score": 10.0,
        "agent2_confidence": 0.95,
    }
    decision = evaluate_review_gate(state)
    assert decision["requires_human_review"] is True
    assert any("Document defect" in r for r in decision["reasons"])
