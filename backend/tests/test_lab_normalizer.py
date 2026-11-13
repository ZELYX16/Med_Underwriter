import pytest
from app.services.lab_normalizer import (
    identify_canonical_biomarker,
    normalize_lab_entry,
    normalize_lab_list,
    parse_blood_pressure,
)

def test_canonical_biomarker_identification():
    assert identify_canonical_biomarker("HbA1c (Glycated Hemoglobin)") == "hba1c"
    assert identify_canonical_biomarker("Fasting Plasma Glucose") == "fasting_glucose"
    assert identify_canonical_biomarker("Serum Creatinine") == "creatinine"
    assert identify_canonical_biomarker("Total Cholesterol") == "total_cholesterol"
    assert identify_canonical_biomarker("Triglycerides") == "triglycerides"

def test_hba1c_conversions():
    # DCCT percentage stays as DCCT
    r1 = normalize_lab_entry("HbA1c", 6.5, "%")
    assert r1.normalized_value == 6.5
    assert r1.normalized_unit == "% (DCCT)"
    assert r1.status == "NORMALIZED"

    # IFCC mmol/mol converts to DCCT %
    # Formula: (IFCC / 10.929) + 2.15 -> (75 / 10.929) + 2.15 = 9.01%
    r2 = normalize_lab_entry("HbA1c", 75, "mmol/mol")
    assert r2.normalized_value == 9.01
    assert r2.normalized_unit == "% (DCCT)"

def test_glucose_conversions():
    # mmol/L to mg/dL: factor 18.0182 -> 7.0 * 18.0182 = 126.1 mg/dL
    r = normalize_lab_entry("Fasting Blood Sugar", 7.0, "mmol/L")
    assert r.normalized_value == 126.1
    assert r.normalized_unit == "mg/dL"

def test_creatinine_conversions():
    # umol/L to mg/dL: 150 / 88.4 = 1.7 mg/dL
    r = normalize_lab_entry("Serum Creatinine", 150, "umol/L")
    assert r.normalized_value == 1.7
    assert r.normalized_unit == "mg/dL"

def test_lipid_conversions():
    # mmol/L to mg/dL: 5.5 * 38.67 = 212.7 mg/dL
    r = normalize_lab_entry("Total Cholesterol", 5.5, "mmol/L")
    assert r.normalized_value == 212.7
    assert r.normalized_unit == "mg/dL"

def test_bounded_comparison_operator():
    r = normalize_lab_entry("Fasting Glucose", "> 180", "mg/dL")
    assert r.normalized_value == 180.0
    assert r.operator == ">"
    assert r.is_bounded is True

def test_qualitative_lab_result():
    r = normalize_lab_entry("Hepatitis B Surface Antigen", "Negative")
    assert r.status == "QUALITATIVE"
    assert r.qualitative_text == "Negative"
    assert r.normalized_value is None

def test_unrecognized_unit_trips_review():
    r = normalize_lab_entry("HbA1c", 7.5, "xyz/L")
    assert r.status == "UNRECOGNIZED_UNIT"
    assert r.requires_human_review is True
    assert "Unrecognized unit" in r.review_reason

def test_blood_pressure_parsing():
    bp = parse_blood_pressure("130/85 mmHg")
    assert bp == (130, 85)
