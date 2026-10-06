# MedUnderwrite AI — Architecture Decisions Log

> Record all significant architecture decisions here as they are made.

## ADR-001 — LLM Provider: Groq
**Decision:** Use Groq (llama-3.1-70b-versatile) as primary LLM.
**Reason:** Free tier available, very low latency, sufficient for demo.
**Trade-off:** Rate limits may require exponential backoff.

## ADR-002 — Vector Store: ChromaDB (local) → Azure AI Search (prod)
**Decision:** PersistentClient locally; HttpClient in Docker/cloud.
**Reason:** Zero-cost local dev; production-grade cloud path.
**Location:** `backend/app/store/chroma_setup.py` + `vector_store.py`

## ADR-003 — Embedding Model: all-MiniLM-L6-v2
**Decision:** Local HuggingFace sentence-transformer.
**Reason:** No API cost; 384-dim vectors sufficient for our collections.

## ADR-004 — State Schema Contract
**Decision:** `UnderwritingState` TypedDict in `models/state.py` is the single
shared contract. Field names must never be changed without notifying both
Persona A and Persona B.

## ADR-005 — Parallel Sub-Agent Execution
**Decision:** Agent 1 uses `asyncio.gather()` for Sub-agents B, C, D in parallel.
**Reason:** Reduces Agent 1 wall-clock time from ~6s to ~2s.

---

*Add new decisions below as they arise during development.*
