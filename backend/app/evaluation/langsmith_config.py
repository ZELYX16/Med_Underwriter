"""
MedUnderwrite AI — LangSmith Tracing Configuration

Owner: Persona A (Day 2 AM)

Configures LangSmith project and tracing:
  - Wraps all LLM calls with trace decorator
  - Tracks: token count, latency, and cost per agent per case
  - Project: "medunderwrite-ai" (set in .env as LANGSMITH_PROJECT)

Environment variables required (.env):
  LANGSMITH_API_KEY=...
  LANGSMITH_PROJECT=medunderwrite-ai
  LANGCHAIN_TRACING_V2=true

TODO (Persona A): connect free LangSmith account, verify traces appear, add cost tracking.
"""
# TODO (Persona A): import langsmith and configure tracing decorators here
