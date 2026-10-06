// MedUnderwrite AI — Root Angular Module
// Owner: Persona B (Day 2 PM)
// TODO: add imports, providers, HttpClientModule, Angular Material modules

import { NgModule } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import { HttpClientModule } from '@angular/common/http';

import { AppRoutingModule } from './app-routing.module';
// TODO (Persona B): import all component modules and Angular Material modules here

@NgModule({
  declarations: [
    // TODO: AppComponent + all 5 components
  ],
  imports: [
    BrowserModule,
    BrowserAnimationsModule,
    HttpClientModule,
    AppRoutingModule,
    // TODO: MatButtonModule, MatFormFieldModule, MatInputModule, MatSelectModule, etc.
  ],
  providers: [],
  bootstrap: [
    // TODO: AppComponent
  ]
})
export class AppModule {}
