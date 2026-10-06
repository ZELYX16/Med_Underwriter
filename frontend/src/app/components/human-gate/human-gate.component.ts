// MedUnderwrite AI — Human Gate Component
// Owner: Persona B (Day 2 PM)
//
// Shows full decision summary + 4 action buttons:
//   ✅ Approve (green)   → POST /api/case/{id}/approve
//   ✏️  Override (yellow) → opens edit dialog → POST /api/case/{id}/override
//   🔄 Send Back (orange) → asks for notes → POST /api/case/{id}/sendback
//   🚨 Escalate (red)    → POST /api/case/{id}/escalate
//
// TODO (Persona B): generate with Angular CLI and implement approval actions.
// ng generate component components/human-gate
