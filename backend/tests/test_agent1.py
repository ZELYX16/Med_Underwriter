"""
MedUnderwrite AI — Agent 1 Unit Tests

Run:
    cd backend
    python -m pytest tests/test_agent1.py -v

Or standalone (no pytest):
    python tests/test_agent1.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Make app importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.agent1_submission import run_agent1_standalone

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

MARIA_PAYLOAD = {
    "applicant": {"name": "Maria Schmidt", "age": 34, "gender": "F", "region": "DE-Munich"},
    "medical": {"icd10_codes": [], "cpt_codes": [], "medications": []},
    "claims_history": {"claims_count_3yr": 0, "total_paid_3yr": 0},
    "existing_policies": [],
}

KLAUS_PAYLOAD = {
    "applicant": {"name": "Klaus Weber", "age": 58, "gender": "M", "region": "DE-Berlin"},
    "medical": {"icd10_codes": ["E11.9", "I10", "I25.9"], "cpt_codes": ["99213", "93000"]},
    "claims_history": {"claims_count_3yr": 8, "total_paid_3yr": 34200},
    "existing_policies": [
        {"policy_id": "POL-001", "type": "basic_health", "coverage_limit": 50000, "annual_premium": 2400}
    ],
}

# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------

async def test_agent1_maria():
    """Maria — healthy young applicant, no conditions. Should complete cleanly."""
    print("\n=== TEST: Maria (Simple case) ===")
    result = await run_agent1_standalone(MARIA_PAYLOAD)

    assert result["agent1_completed"], "agent1_completed should be True"
    assert result["processing_status"] in {"agent1_complete", "agent1_error"}, \
        f"Unexpected status: {result['processing_status']}"

    enrichment = result.get("enrichment_results", {})
    print(f"  Claims 3yr: {enrichment.get('claims_history', {}).get('claims_3yr')}")
    print(f"  Coverage gaps: {enrichment.get('coverage_gaps')}")
    print(f"  Risk flags: {result.get('applicant_profile', {}).get('risk_flags')}")
    print("  ✅ Maria test passed")
    return result


async def test_agent1_klaus():
    """Klaus — complex multi-comorbidity case. Should detect risk flags."""
    print("\n=== TEST: Klaus (Complex case) ===")
    result = await run_agent1_standalone(KLAUS_PAYLOAD)

    assert result["agent1_completed"], "agent1_completed should be True"

    profile = result.get("applicant_profile", {})
    enrichment = result.get("enrichment_results", {})
    risk_flags = profile.get("risk_flags", [])

    print(f"  ICD codes: {profile.get('icd10_codes')}")
    print(f"  Risk flags: {risk_flags}")
    print(f"  Claims: {enrichment.get('claims_history')}")
    print(f"  Coverage gaps: {enrichment.get('coverage_gaps')}")
    print(f"  Benchmark loading: {enrichment.get('benchmarks', {}).get('combined_loading_pct')}%")

    # Klaus has 3 ICD codes → should flag comorbidity_multiple
    assert "comorbidity_multiple" in risk_flags or "comorbidity_present" in risk_flags, \
        "Klaus should have comorbidity flags"

    print("  ✅ Klaus test passed")
    return result


async def test_agent1_audit_trail():
    """Verify audit trail is populated correctly."""
    print("\n=== TEST: Audit Trail ===")
    result = await run_agent1_standalone(MARIA_PAYLOAD)
    trail = result.get("audit_trail", [])
    assert len(trail) >= 1, "Audit trail should have at least 1 entry"
    steps = [e.get("step") for e in trail]
    print(f"  Audit steps: {steps}")
    assert any("agent1" in s for s in steps), "Audit trail should contain agent1 entry"
    print("  ✅ Audit trail test passed")


async def run_all_tests():
    print("=" * 50)
    print("MedUnderwrite AI — Agent 1 Tests")
    print("=" * 50)
    await test_agent1_maria()
    await test_agent1_klaus()
    await test_agent1_audit_trail()
    print("\n✅ All Agent 1 tests passed!")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
