"""
MedUnderwrite AI — Human-in-the-Loop (HITL) Tests

Owner: Persona B (Day 2 PM)

Tests:
  - Graph pauses at human_gate node (interrupt_before)
  - Human approve → case reaches END
  - Human send-back → case returns to Agent 2 with feedback
  - Human escalate → case reaches human_escalation node

TODO (Persona B): implement after HITL gate is wired in graph.py.

Run:
    python -m pytest tests/test_hitl.py -v
"""
# TODO (Persona B): import graph and write HITL interrupt/resume test cases here
