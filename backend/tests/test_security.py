"""
MedUnderwrite AI — Security / NeMo Guardrails Tests

Owner: Persona A (Day 2 AM)

Tests:
  - Malicious prompt injection → blocked ✅
  - PII (raw SSN pattern) → detected and blocked ✅
  - Clean medical query → passes through ✅
  - Output PHI leakage detection ✅

TODO (Persona A): implement test cases once guardrails.py is done.

Run:
    python -m pytest tests/test_security.py -v
"""
# TODO (Persona A): import guardrails and write test cases here
