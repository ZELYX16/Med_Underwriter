// MedUnderwrite AI — Underwriting Service
// Owner: Persona B (Day 2 PM)
//
// HTTP calls to FastAPI backend + WebSocket for real-time status:
//   POST /api/underwrite          → startCase(request)
//   GET  /api/case/{case_id}      → getCase(caseId)
//   POST /api/case/{id}/approve   → approveCase(caseId, body)
//   POST /api/case/{id}/override  → overrideCase(caseId, body)
//   POST /api/case/{id}/sendback  → sendBack(caseId, body)
//   POST /api/case/{id}/escalate  → escalateCase(caseId, body)
//   WS   /ws/status/{case_id}     → connectStatusSocket(caseId): Observable<AgentStatusUpdate>
//
// TODO (Persona B): implement all HTTP methods and WebSocket observable.

import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../environments/environment';

@Injectable({ providedIn: 'root' })
export class UnderwriteService {
  private apiUrl = environment.apiUrl;

  constructor(private http: HttpClient) {}

  // TODO (Persona B): implement service methods here
}
