import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import { QuestionnaireData } from '../core/api.models';
import { SmartCounsellingApiService } from '../core/smart-counselling-api.service';
import { CounsellingStepperComponent } from '../shared/counselling-stepper.component';
import { PageHeaderComponent } from '../shared/page-header.component';

@Component({selector: 'sc-goals', imports: [ReactiveFormsModule, RouterLink, CounsellingStepperComponent, PageHeaderComponent], templateUrl: './goals.component.html', changeDetection: ChangeDetectionStrategy.OnPush})
export class GoalsComponent implements OnInit {
  private readonly api = inject(SmartCounsellingApiService); private readonly route = inject(ActivatedRoute); private readonly router = inject(Router);
  readonly sessionId = Number(this.route.snapshot.paramMap.get('sessionId'));
  readonly loading = signal(true); readonly saving = signal(false); readonly error = signal(''); readonly questionnaire = signal<QuestionnaireData | null>(null);
  readonly interests = signal<string[]>([]);
  readonly primaryGoal = new FormControl('', {nonNullable: true, validators: [Validators.required]});
  readonly startTimeframe = new FormControl('', {nonNullable: true, validators: [Validators.required]});
  readonly preferredDuration = new FormControl('', {nonNullable: true}); readonly preferredTiming = new FormControl('', {nonNullable: true});
  readonly preferredLearningMode = new FormControl('', {nonNullable: true}); readonly preferredLanguage = new FormControl('', {nonNullable: true});

  ngOnInit(): void { forkJoin({q: this.api.getQuestionnaire(), a: this.api.getAssessment(this.sessionId)}).subscribe({next: ({q, a}) => { if (!a.profileComplete) { this.router.navigate(['/session', this.sessionId, 'profile']); return; } this.questionnaire.set(q); this.primaryGoal.setValue(String(a.answers['primary_goal'] ?? '')); this.startTimeframe.setValue(String(a.answers['start_timeframe'] ?? '')); this.interests.set((a.answers['interests'] as string[]) ?? []); this.preferredDuration.setValue(String(a.answers['preferred_duration'] ?? '')); this.preferredTiming.setValue(String(a.answers['preferred_timing'] ?? '')); this.preferredLearningMode.setValue(String(a.answers['preferred_learning_mode'] ?? '')); this.preferredLanguage.setValue(String(a.answers['preferred_language'] ?? '')); this.loading.set(false); }, error: (error: Error) => { this.error.set(error.message); this.loading.set(false); }}); }
  toggleInterest(code: string): void { this.interests.update((items) => items.includes(code) ? items.filter((item) => item !== code) : [...items, code]); }
  save(): void { if (this.primaryGoal.invalid || this.startTimeframe.invalid || !this.interests().length || this.saving()) { this.error.set('Choose a primary goal, at least one interest, and a start timeframe.'); return; } this.saving.set(true); this.error.set(''); const answers: Record<string, string | string[]> = {primary_goal: this.primaryGoal.value, interests: this.interests(), start_timeframe: this.startTimeframe.value}; if (this.preferredDuration.value) answers['preferred_duration'] = this.preferredDuration.value; if (this.preferredTiming.value) answers['preferred_timing'] = this.preferredTiming.value; if (this.preferredLearningMode.value) answers['preferred_learning_mode'] = this.preferredLearningMode.value; if (this.preferredLanguage.value) answers['preferred_language'] = this.preferredLanguage.value; this.api.saveAssessment(this.sessionId, answers).subscribe({next: () => this.router.navigate(['/session', this.sessionId, 'skills']), error: (error: Error) => { this.error.set(error.message); this.saving.set(false); }}); }
}
