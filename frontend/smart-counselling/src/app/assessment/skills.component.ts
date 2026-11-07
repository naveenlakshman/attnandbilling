import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import { QuestionnaireData } from '../core/api.models';
import { SmartCounsellingApiService } from '../core/smart-counselling-api.service';
import { CounsellingStepperComponent } from '../shared/counselling-stepper.component';
import { PageHeaderComponent } from '../shared/page-header.component';

@Component({selector: 'sc-skills', imports: [ReactiveFormsModule, RouterLink, CounsellingStepperComponent, PageHeaderComponent], templateUrl: './skills.component.html', changeDetection: ChangeDetectionStrategy.OnPush})
export class SkillsComponent implements OnInit {
  private readonly api = inject(SmartCounsellingApiService); private readonly route = inject(ActivatedRoute); private readonly router = inject(Router);
  readonly sessionId = Number(this.route.snapshot.paramMap.get('sessionId')); readonly loading = signal(true); readonly saving = signal(false); readonly error = signal(''); readonly questionnaire = signal<QuestionnaireData | null>(null); readonly programmingSelected = signal(false);
  readonly computer = new FormControl('', {nonNullable: true, validators: [Validators.required]}); readonly accounting = new FormControl('', {nonNullable: true, validators: [Validators.required]}); readonly excel = new FormControl('', {nonNullable: true, validators: [Validators.required]}); readonly english = new FormControl('', {nonNullable: true, validators: [Validators.required]}); readonly programming = new FormControl('', {nonNullable: true});
  ngOnInit(): void { forkJoin({q: this.api.getQuestionnaire(), a: this.api.getAssessment(this.sessionId)}).subscribe({next: ({q, a}) => { if (!a.profileComplete) { this.router.navigate(['/session', this.sessionId, 'profile']); return; } if (!a.answers['primary_goal']) { this.router.navigate(['/session', this.sessionId, 'goals']); return; } this.questionnaire.set(q); this.programmingSelected.set(((a.answers['interests'] as string[]) ?? []).includes('PROGRAMMING')); this.computer.setValue(String(a.answers['computer_skill'] ?? '')); this.accounting.setValue(String(a.answers['accounting_skill'] ?? '')); this.excel.setValue(String(a.answers['excel_skill'] ?? '')); this.english.setValue(String(a.answers['english_skill'] ?? '')); this.programming.setValue(String(a.answers['programming_experience'] ?? '')); this.loading.set(false); }, error: (error: Error) => { this.error.set(error.message); this.loading.set(false); }}); }
  select(control: FormControl<string>, code: string): void { control.setValue(code); }
  save(): void { if ([this.computer, this.accounting, this.excel, this.english].some((control) => control.invalid) || (this.programmingSelected() && !this.programming.value)) { this.error.set('Complete each required skill level.'); return; } this.saving.set(true); this.error.set(''); const answers: Record<string, string> = {computer_skill: this.computer.value, accounting_skill: this.accounting.value, excel_skill: this.excel.value, english_skill: this.english.value}; if (this.programmingSelected()) answers['programming_experience'] = this.programming.value; this.api.saveAssessment(this.sessionId, answers, true).subscribe({next: () => this.router.navigate(['/session', this.sessionId, 'recommendations']), error: (error: Error) => { this.error.set(error.message); this.saving.set(false); }}); }
}
