// MedUnderwrite AI — Angular Routing Module
// Owner: Persona B (Day 2 PM)
// Routes: / → SubmissionForm, /results → ResultsDashboard,
//          /approve → HumanGate, /trace → AgentTrace

import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';

const routes: Routes = [
  // TODO (Persona B): add routes once components are generated
  // { path: '', component: SubmissionFormComponent },
  // { path: 'results', component: ResultsDashboardComponent },
  // { path: 'approve', component: HumanGateComponent },
  // { path: 'trace', component: AgentTraceComponent },
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule]
})
export class AppRoutingModule {}
