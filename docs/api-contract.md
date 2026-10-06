# MedUnderwrite AI — Full API Contract

> This is the agreed contract between Persona A (backend) and Persona B (frontend).
> Agree on this before Day 1 — both can work independently once this is set.

## Base URLs
| Environment | URL |
|---|---|
| Local | `http://localhost:8000` |
| AWS Demo | `http://{ec2-public-ip}:8000` |
| Production | `https://api.medunderwrite.allianz.com` |

**All requests:** `Content-Type: application/json`
**All responses:** `{ "success": bool, "data": {...} | null, "error": string | null }`

---

## Endpoints

### POST `/api/underwrite` — Start Underwriting Case
See developer guide Section 6.2 for full request/response JSON.

### GET `/api/case/{case_id}` — Get Case Status & Results
See developer guide Section 6.3 for full response JSON.

### POST `/api/case/{case_id}/approve`
### POST `/api/case/{case_id}/override`
### POST `/api/case/{case_id}/sendback`
### POST `/api/case/{case_id}/escalate`
See developer guide Section 6.4 for request/response shapes.

### WebSocket `/ws/status/{case_id}` — Real-Time Progress
See developer guide Section 6.5 for message type definitions.

### GET `/api/health` — System Health Check
See developer guide Section 6.6 for response shape.

---

## State field names (DO NOT rename — shared contract between agents)
See `backend/app/models/state.py` for the canonical `UnderwritingState` TypedDict.
