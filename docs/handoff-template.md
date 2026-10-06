# MedUnderwrite AI — Shift Handoff Note Template

```
📋 HANDOFF NOTE — [Date] [Time]
─────────────────────────────────────────────
WHAT I BUILT:
  - [Component 1]: COMPLETE ✅ — [file path]
  - [Component 2]: COMPLETE ✅ — [file path]

HOW TO VERIFY:
  1. git pull origin main
  2. pip install -r backend/requirements.txt   (if new deps added)
  3. python backend/tests/test_[component].py

YOUR TASKS TODAY:
  - [Task 1]: Build in [file path]
  - [Task 2]: Build in [file path]

⚠️ WATCH OUT:
  - [Any known issues, dependencies, or gotchas]
  - State schema is in models/state.py — do NOT rename fields!
  - Groq API key is in .env as GROQ_API_KEY

QUICK START:
  cd backend && uvicorn app.main:app --reload
─────────────────────────────────────────────
```

## Day 1 AM → PM Handoff Checklist (Persona A → Persona B)
- [ ] ChromaDB seeded — `python backend/scripts/load_data.py` passes
- [ ] RAG test passes — `python -m pytest backend/tests/test_rag.py`
- [ ] Agent 1 test passes — `python -m pytest backend/tests/test_agent1.py`
- [ ] FastAPI starts — `uvicorn app.main:app --reload` with no errors
- [ ] `/api/health` returns `{"status": "healthy"}`

## Day 2 AM → PM Handoff Checklist (Persona A → Persona B)
- [ ] Full flow test passes — `python -m pytest backend/tests/test_flow.py`
- [ ] Security test passes — `python -m pytest backend/tests/test_security.py`
- [ ] RAGAS scores printed and saved
- [ ] `docs/api-responses.json` updated with real outputs
