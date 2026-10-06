# MedUnderwrite AI

> Health Insurance Underwriting powered by LangGraph multi-agent AI.
> Built for Allianz Technology SE — 2-Day Sprint Project.

## Stack
- **Backend:** Python · FastAPI · LangGraph · LangChain · ChromaDB
- **Frontend:** Angular 17 · Angular Material
- **LLM:** Groq (llama-3.1-70b-versatile)
- **Infra:** Docker · GitHub Actions · AWS EC2

## Architecture
Three specialized agents orchestrated by LangGraph:
1. **Agent 1 — Submission Intelligence** (ReAct): enriches submission with EHR, claims, regulatory, benchmarks, coverage gaps
2. **Agent 2 — Risk Assessment & Pricing** (Plan-and-Execute / Tree-of-Thought): scores risk and calculates premium
3. **Agent 3 — Reflection & Advisory** (Constitutional AI + MAR): validates decision, runs multi-persona debate

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env — add GROQ_API_KEY

# 2. Install backend dependencies
cd backend
pip install -r requirements.txt

# 3. Seed vector database
python scripts/load_data.py

# 4. Start backend
uvicorn app.main:app --reload

# 5. Or start everything with Docker
docker-compose up --build
```

## Demo Scenarios
| Scenario | Applicant | Complexity | Expected Outcome |
|---|---|---|---|
| Maria | 34F, no conditions | Simple | ACCEPT, base premium |
| Klaus | 58M, diabetes + hypertension + cardiac | Complex | ACCEPT WITH LOADING, MAR debate |
| Stefan | 62M, cancer history + multiple comorbidities | High-Risk | HITL fast-track |


