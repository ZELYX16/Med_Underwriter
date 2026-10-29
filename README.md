# MedUnderwrite AI
> Health insurance underwriting decision support powered by a LangGraph multi-agent workflow.
> Built for Allianz Technology SE as a 2-day sprint project.
The system ingests an applicant's submission and documents, enriches it with retrieved evidence, scores risk and prices the policy, critiques its own decision, and routes risky or low-confidence cases to a human underwriter.
## Stack
- **Backend:** Python 3.11+, FastAPI, LangGraph, LangChain, ChromaDB, SQLite
- **Frontend:** Streamlit (underwriting workstation)
- **LLM:** pluggable via `LLM_PROVIDER`: `ollama` (default, local), `groq`, or `gemini`
- **Embeddings:** `BAAI/bge-small-en-v1.5` (local sentence-transformers)
- **Evaluation / tracing:** RAGAS, DeepEval, LangSmith
- **Infra:** Docker, GitHub Actions, AWS EC2 (deployment files are still partly stubs, see [Status](#status))
## Architecture
A compiled LangGraph `StateGraph` over a shared `UnderwritingState` (`backend/app/models/state.py`):
```
intake → agent1_submission → complexity_router → agent2_risk → confidence_gate
       → agent3_reflection → { rescore → agent2_risk | human_review | finalize }
```
1. **Agent 1, Submission Intelligence:** gathers medical, claims, policy, regulatory and underwriting-knowledge evidence through the RAG layer and produces an enrichment plus coverage gaps.
2. **Complexity router:** a weighted score over explainable signals (conditions, high-risk keywords, conflicting evidence, claims, hospitalizations, medications, age, BMI, smoker, sum insured). Score 0 is `simple`, `router_complex_threshold` (default 4) or more is `complex`, anything between is `standard`. High-risk keywords or conflicting evidence always force `complex`. The score breakdown is stored in the workflow trace.
3. **Agent 2, Risk Assessment & Pricing:** risk scores, base premium and loading, a recommendation (`standard_acceptance`, `accept_with_loading`, `accept_with_exclusion`, `postpone`, `decline`, `human_review`) and a confidence value are computed in code. The LLM only writes a short assessment, and is skipped for simple low-risk cases or when an identical decision was already explained (rationale cache). A fact-exact structured breakdown (`reasoning_structured`) is built from the same values as the scores. Deterministic fraud-risk indicators (`agents/fraud.py`) flag cases for a human and never decline automatically.
4. **Agent 3, Reflection & Advisory:** mandatory rule-based critique using a multi-persona review (MAR) and constitutional checks (medical accuracy, actuarial soundness, regulatory compliance, fairness, explainability). For complex or high-risk cases it adds an LLM critique of the decision and rationale (`agents/reflection/llm_critic.py`). The critique is skipped when the rules already require human review, can only add caution (an explicit "disagree" forces human review), and never lowers a score. It can send the case back to Agent 2 for a rescore, capped at 3 rounds.
5. **Human-review gating:** a central rule set overrides the agents' recommendation and forces human review when, for example, medical risk is 80 or higher, overall risk is 70 or higher, confidence is below 0.70, a constitutional flag is raised, reflection failed, or there is no consensus at the round limit.
Supporting layers:
- **RAG (`app/rag/`):** hybrid, corrective (CRAG), agentic and graph-style (MedGraph) retrieval, selected by a query classifier. Per-applicant filtered search over uploaded documents.
- **Stores (`app/store/`):** ChromaDB for vectors, SQLite for applicants, cases and workflow state.
- **Cache (`app/cache/pattern_cache.py`):** a persistent SQLite pattern cache with two namespaces: `rationale` (Agent 2's explanation, keyed by a hash of the exact facts, scores, pricing and recommendation) and `knowledge` (regulatory and guidance lookups, keyed by product and condition categories). Each entry records the case that stored it, and the case's **Cache** tab shows hits, misses and a button to open the matched case. `semantic_cache.py` is an unused stub.
- **Batch mode (`app/services/batch.py`, `similarity.py`):** the UI proposes groups of similar draft cases (same product, condition categories and age band) with the reason for each group. Only the groups you approve run. Groups share regulatory/guidance retrieval and query embeddings; every case still gets its own scoring, rationale and review. Concurrency is bounded (`batch_concurrency`, default 2).
- **Security (`app/security/`):** input/output guardrails configured in `config/guardrails.yml`, an index-time scan that flags document chunks containing injected instructions or secrets, an upload size cap (`max_upload_mb`) and filename sanitizing.
- **Evaluation (`app/evaluation/`):** RAGAS and DeepEval suites; results are written to `app/evaluation/results/`.
More detail: `CLAUDE.md`, `backend/CLAUDE.md`, `docs/architecture.md`, `docs/api-contract.md`.
## Quick Start
```bash
# 1. Configure
cp .env.example .env
# Default is a local Ollama setup (see OLLAMA_BASE_URL and the *_MODEL variables).
# For Groq or Gemini set LLM_PROVIDER plus the matching API key and all three model names.
# 2. Backend
cd backend
pip install -r requirements.txt
python -m app.services.seed_database    # seed SQLite
python -m app.services.index_data       # index documents into ChromaDB
uvicorn app.main:app --reload --port 8000
# API docs: http://localhost:8000/docs   Health: http://localhost:8000/health
# 3. Frontend (new terminal)
cd frontend
pip install -r requirements.txt
streamlit run app.py
```
The frontend reads `MEDUNDERWRITE_BACKEND_URL` (default `http://127.0.0.1:8000`) and `MEDUNDERWRITE_REQUEST_TIMEOUT` (default 30 seconds).
With Ollama, pull the models named in `.env` first (for example `ollama pull qwen2.5:3b` and `ollama pull gemma3:4b`). On startup the backend preloads the reasoning and reflection models (`warm_llm_on_startup`, Ollama only).
### Optional: scenario applicants
Five synthetic applicants (`APP-011` to `APP-015`) exercise features the base demo data does not trigger:
```bash
cd backend
python -m scripts.create_scenario_data   # needs reportlab; writes where the seeder reads
python -m app.services.seed_database
python -m app.services.index_data
```
## Performance notes
- Agent 1 makes no LLM call. Agent 2 makes at most one short call. Agent 3's LLM critique runs only for complex or high-risk cases that the rules do not already escalate.
- `ollama_num_ctx`, `reasoning_max_tokens` and `reflection_max_tokens` keep local calls short. Use one model for all roles to avoid model reloads.
- The Workflow tab shows, per agent: total latency, estimated data tokens in/out, LLM status (used, skipped, cache hit, rejected, failed), LLM tokens and latency, and Ollama load/generation timings and tokens per second.
- A local model serves LLM calls largely one at a time, so batch mode does not make a single case faster. It helps throughput with a hosted provider.
## API
All routes are mounted under `/api`. Main groups:
| Area | Endpoints |
|---|---|
| Applicants | `GET/POST /applicants`, `GET /applicants/{id}` |
| Cases | `GET/POST /cases`, `GET /case/{id}`, `GET /case/{id}/status`, `GET /case/{id}/events`, `GET /case/{id}/cache` |
| Batch | `POST /cases/batch/plan` (propose groups with reasons), `POST /cases/batch` |
| Documents | `GET/POST /case/{id}/documents`, `DELETE /case/{id}/documents/{document_id}` |
| Run workflow | `POST /case/{id}/start`, `POST /underwrite`, WebSocket `/ws/status/{case_id}` |
| Human review | `GET /case/{id}/reviews`, `POST /case/{id}/approve`, `/override`, `/sendback`, `/escalate` |
## Tests and Evaluation
```bash
cd backend
python -m pytest tests/ -v                  # all tests
python -m pytest tests/test_flow.py -v      # one file
python -m app.evaluation.ragas_eval         # RAG quality
python -m app.evaluation.deepeval_suite
```
Tests exercise the real agents and RAG layer, so they need a reachable LLM provider and an indexed ChromaDB store.
## Demo Scenarios
| Scenario | Applicant | Complexity | Expected Outcome |
|---|---|---|---|
| Maria | 34F, no conditions | Simple | Standard acceptance, base premium |
| Klaus | 58M, diabetes + hypertension + cardiac | Complex | Accept with loading, MAR debate |
| Stefan | 62M, cancer history + multiple comorbidities | High-risk | Human review (fast-track) |
Scenario applicants (see [Optional: scenario applicants](#optional-scenario-applicants)):
| Case | Purpose | Expected |
|---|---|---|
| UW-011, UW-012 | Cache twins (identical facts) | Run 011 then 012: the second reuses the cached rationale and knowledge lookups. They are also grouped by batch planning. |
| UW-013 | Fraud indicators | Undeclared conditions and smoking, repeated and duplicate claims: high fraud score, human review |
| UW-014 | Security | Submission note with injected instructions, a key and personal identifiers is blocked by the guardrails; a hidden instruction in the medical report is flagged at indexing |
| UW-015 | Coverage / evidence gap | No medical or claims documents and a policy that excludes the condition |
## Status
- `backend/Dockerfile` builds the API (python:3.11-slim, uvicorn on 8000).
- `docker-compose.yml` references a `./frontend` build that has no Dockerfile yet, so the Docker path currently covers the backend only.
- `.github/workflows/deploy.yml` and `deployment/` are scaffolds: CI does not yet run tests or deploy.
- `backend/scripts/load_data.py` is stale; use `app/services/*` for seeding and indexing.
- The API has no authentication or role checks yet; `SECRET_KEY` defaults to a development value (a warning is logged outside development).
CV