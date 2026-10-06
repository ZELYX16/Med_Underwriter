from pathlib import Path
from textwrap import dedent

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data" / "synthetic"


def create_pdf(
    path: Path,
    title: str,
    sections: list[tuple[str, str]],
):
    path.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()

    title_style = styles["Title"]
    heading_style = styles["Heading2"]
    body_style = styles["BodyText"]

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    story = [
        Paragraph(title, title_style),
        Spacer(1, 8),
    ]

    for heading, content in sections:
        story.append(
            Paragraph(heading, heading_style)
        )
        story.append(
            Paragraph(
                content.replace("\n", "<br/>"),
                body_style,
            )
        )
        story.append(Spacer(1, 8))

    story.append(
        Paragraph(
            "SYNTHETIC / DEMONSTRATION DATA — "
            "MEDUNDERWRITE AI",
            styles["Italic"],
        )
    )

    doc.build(story)


def create_applicant_001():
    root = (
        DATA_ROOT
        / "applicants"
        / "APP-TEST-001"
    )

    create_pdf(
        root
        / "medical"
        / "MR-TEST-001_medical_examination.pdf",
        "Medical Examination Report",
        [
            (
                "Applicant",
                "Applicant ID: APP-TEST-001\n"
                "Name: Priya Menon\n"
                "Age: 31\n"
                "Sex: Female\n"
                "Occupation: Software Engineer",
            ),
            (
                "Clinical Summary",
                "No known chronic medical conditions. "
                "No previous major hospitalization. "
                "No current prescription medication.",
            ),
            (
                "Lifestyle",
                "Non-smoker. Occasional alcohol consumption. "
                "BMI: 22.4.",
            ),
            (
                "Assessment",
                "Routine medical examination. "
                "No significant abnormality identified "
                "in the submitted synthetic record.",
            ),
        ],
    )

    create_pdf(
        root
        / "policy"
        / "POL-TEST-001_existing_policy.pdf",
        "Existing Policy Schedule",
        [
            (
                "Policy Details",
                "Policy ID: POL-TEST-001\n"
                "Applicant ID: APP-TEST-001\n"
                "Insurer: Demo Health Assurance\n"
                "Policy Type: Individual Health\n"
                "Sum Insured: INR 500,000\n"
                "Status: Active",
            ),
            (
                "Claims",
                "Declared claims: None.",
            ),
        ],
    )

    create_pdf(
        root
        / "underwriting"
        / "UW-TEST-001_submission.pdf",
        "Underwriting Submission Request",
        [
            (
                "Submission",
                "Submission ID: UW-TEST-001\n"
                "Applicant ID: APP-TEST-001\n"
                "Requested Product: MedShield Comprehensive\n"
                "Requested Sum Insured: INR 1,000,000\n"
                "Policy Term: 1 year.",
            ),
            (
                "Applicant Declaration",
                "Applicant has declared no chronic "
                "medical condition, no ongoing treatment, "
                "and no significant hospitalization history.",
            ),
        ],
    )


def create_applicant_002():
    root = (
        DATA_ROOT
        / "applicants"
        / "APP-TEST-002"
    )

    create_pdf(
        root
        / "medical"
        / "MR-TEST-002_medical_examination.pdf",
        "Medical Examination Report",
        [
            (
                "Applicant",
                "Applicant ID: APP-TEST-002\n"
                "Name: Rahul Varma\n"
                "Age: 59\n"
                "Sex: Male\n"
                "Occupation: Business Owner",
            ),
            (
                "Medical Conditions",
                "Type 2 diabetes mellitus.\n"
                "Essential hypertension.\n"
                "Dyslipidaemia.\n"
                "Coronary artery disease with previous "
                "myocardial infarction and angioplasty.",
            ),
            (
                "Medication",
                "Metformin 500 mg twice daily.\n"
                "Amlodipine 5 mg daily.\n"
                "Atorvastatin 40 mg daily.\n"
                "Aspirin 75 mg daily.\n"
                "Metoprolol 50 mg daily.",
            ),
            (
                "Lifestyle",
                "Former smoker. Occasional alcohol consumption. "
                "BMI: 29.3.",
            ),
        ],
    )

    create_pdf(
        root
        / "medical"
        / "MR-TEST-002_cardiology_report.pdf",
        "Cardiology Follow-up Report",
        [
            (
                "Clinical History",
                "History of myocardial infarction treated with "
                "coronary angioplasty and one stent.",
            ),
            (
                "Current Status",
                "Applicant is under continuing cardiology "
                "follow-up. No acute event is documented "
                "in the current synthetic report.",
            ),
            (
                "Risk Factors",
                "Diabetes, hypertension, dyslipidaemia, "
                "previous smoking history and established "
                "coronary artery disease.",
            ),
        ],
    )

    create_pdf(
        root
        / "claims"
        / "CLM-TEST-002_cardiac_claim.pdf",
        "Synthetic Claim Record",
        [
            (
                "Claim Details",
                "Claim ID: CLM-TEST-002\n"
                "Applicant ID: APP-TEST-002\n"
                "Claim Type: Hospitalization\n"
                "Diagnosis: Acute myocardial infarction\n"
                "Claim Status: Settled",
            ),
            (
                "Event",
                "Synthetic hospitalization associated with "
                "the applicant's cardiac history.",
            ),
        ],
    )

    create_pdf(
        root
        / "claims"
        / "CLM-TEST-002_diabetes_claim.pdf",
        "Synthetic Claim Record",
        [
            (
                "Claim Details",
                "Claim ID: CLM-TEST-003\n"
                "Applicant ID: APP-TEST-002\n"
                "Claim Type: Outpatient management\n"
                "Diagnosis: Type 2 diabetes\n"
                "Claim Status: Settled",
            ),
        ],
    )

    create_pdf(
        root
        / "policy"
        / "POL-TEST-002_existing_policy.pdf",
        "Existing Policy Schedule",
        [
            (
                "Policy Details",
                "Policy ID: POL-TEST-002\n"
                "Applicant ID: APP-TEST-002\n"
                "Insurer: Demo Health Assurance\n"
                "Policy Type: Individual Health\n"
                "Sum Insured: INR 500,000\n"
                "Status: Active.",
            ),
            (
                "Claims History",
                "Multiple declared claims are present "
                "in the submitted synthetic record.",
            ),
        ],
    )

    create_pdf(
        root
        / "underwriting"
        / "UW-TEST-002_submission.pdf",
        "Underwriting Submission Request",
        [
            (
                "Submission",
                "Submission ID: UW-TEST-002\n"
                "Applicant ID: APP-TEST-002\n"
                "Requested Product: MedShield Comprehensive\n"
                "Requested Sum Insured: INR 2,000,000\n"
                "Policy Term: 1 year.",
            ),
            (
                "Underwriting Note",
                "Submission contains multiple chronic "
                "conditions, previous cardiac intervention, "
                "multiple medications and declared claims.",
            ),
        ],
    )


def create_knowledge_documents():
    knowledge_root = (
        DATA_ROOT
        / "underwriting"
    )

    create_pdf(
        knowledge_root
        / "guidelines"
        / "UW-DEMO-001_underwriting_guidelines.pdf",
        "Synthetic Underwriting Guidelines",
        [
            (
                "Purpose",
                "This document is synthetic demonstration "
                "data for MedUnderwrite AI. It is not an "
                "official insurance regulation.",
            ),
            (
                "Low Complexity",
                "Applicants with no significant chronic "
                "conditions and limited medical history "
                "may proceed through standard assessment.",
            ),
            (
                "Higher Complexity",
                "Multiple chronic conditions, significant "
                "cardiac history, repeated claims or "
                "insufficient evidence should receive "
                "additional underwriting review.",
            ),
            (
                "Human Review",
                "Human review should be considered when "
                "medical evidence is insufficient, risk "
                "is materially elevated, or the automated "
                "system has low confidence.",
            ),
        ],
    )

    create_pdf(
        knowledge_root
        / "rules"
        / "PR-DEMO-001_pricing_rules.pdf",
        "Synthetic Pricing Rules",
        [
            (
                "Important Notice",
                "Synthetic demonstration pricing rules only. "
                "These rules do not represent an insurer's "
                "actual actuarial methodology.",
            ),
            (
                "Base Premium",
                "Demonstration base premium may be calculated "
                "as a percentage of the requested sum insured "
                "for testing purposes.",
            ),
            (
                "Risk Loading",
                "Higher assessed risk may result in a "
                "demonstration loading. Production pricing "
                "must use approved actuarial pricing models "
                "and business rules.",
            ),
        ],
    )

    create_pdf(
        knowledge_root
        / "guidelines"
        / "REG-DEMO-001_regulatory_reference.pdf",
        "Synthetic Regulatory Reference",
        [
            (
                "Important Notice",
                "This is synthetic test content created only "
                "for software development and retrieval "
                "testing. It is NOT an IRDAI regulation.",
            ),
            (
                "Evidence",
                "Regulatory conclusions in production must "
                "be supported by the applicable official "
                "regulatory source.",
            ),
            (
                "Human Oversight",
                "Uncertain regulatory interpretation should "
                "be escalated to an appropriate human reviewer.",
            ),
        ],
    )


def create_medical_knowledge():
    root = (
        DATA_ROOT
        / "evaluation"
        / "medical_knowledge"
    )

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    content = dedent(
        """
        SYNTHETIC MEDICAL KNOWLEDGE — TEST DATA

        Type 2 diabetes mellitus:
        A chronic metabolic condition associated with
        elevated blood glucose. Long-term management may
        include lifestyle intervention and medication.

        Essential hypertension:
        A chronic condition involving elevated blood
        pressure. Risk assessment may consider duration,
        treatment and associated cardiovascular conditions.

        Coronary artery disease:
        A cardiovascular condition involving disease of
        the coronary arteries. Previous myocardial
        infarction and coronary intervention may be
        important clinical history for underwriting review.

        IMPORTANT:
        This document is synthetic demonstration data.
        It must not be treated as clinical guidance.
        """
    ).strip()

    (root / "medical_knowledge.txt").write_text(
        content,
        encoding="utf-8",
    )


def main():
    create_applicant_001()
    create_applicant_002()
    create_knowledge_documents()
    create_medical_knowledge()

    print("Synthetic test data created successfully.")
    print()
    print(
        f"Location: {DATA_ROOT}"
    )
    print()
    print("Applicants:")
    print("  APP-TEST-001")
    print("  APP-TEST-002")
    print()
    print("Knowledge:")
    print("  Synthetic underwriting guidelines")
    print("  Synthetic pricing rules")
    print("  Synthetic regulatory reference")
    print("  Synthetic medical knowledge")


if __name__ == "__main__":
    main()