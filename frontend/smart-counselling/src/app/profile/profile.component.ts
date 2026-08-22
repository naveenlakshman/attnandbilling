import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import { ProspectProfile, QuestionnaireData } from '../core/api.models';
import { SmartCounsellingApiService } from '../core/smart-counselling-api.service';
import { CounsellingStepperComponent } from '../shared/counselling-stepper.component';
import { PageHeaderComponent } from '../shared/page-header.component';

@Component({
  selector: 'sc-profile',
  imports: [ReactiveFormsModule, RouterLink, CounsellingStepperComponent, PageHeaderComponent],
  templateUrl: './profile.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfileComponent implements OnInit {
  private readonly api = inject(SmartCounsellingApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  readonly sessionId = Number(this.route.snapshot.paramMap.get('sessionId'));
  readonly loading = signal(true); readonly saving = signal(false); readonly error = signal('');
  readonly questionnaire = signal<QuestionnaireData | null>(null);
  readonly existingLead = signal(false); readonly locked = signal(false);
  readonly confirmChanges = new FormControl(false, {nonNullable: true});
  private initial: ProspectProfile | null = null;

  readonly name = new FormControl('', {nonNullable: true, validators: [Validators.required, Validators.minLength(2), Validators.maxLength(120)]});
  readonly age = new FormControl<number | null>(null, [Validators.required, Validators.min(12), Validators.max(100)]);
  readonly educationStatus = new FormControl('', {nonNullable: true, validators: [Validators.required]});
  readonly qualification = new FormControl('', {nonNullable: true, validators: [Validators.required]});
  readonly qualificationOther = new FormControl('', {nonNullable: true});
  readonly stream = new FormControl('', {nonNullable: true});
  readonly institution = new FormControl('', {nonNullable: true});
  readonly currentYear = new FormControl('', {nonNullable: true});
  readonly currentSituation = new FormControl('', {nonNullable: true, validators: [Validators.required]});
  readonly email = new FormControl('', {nonNullable: true, validators: [Validators.email]});
  readonly whatsapp = new FormControl('', {nonNullable: true, validators: [Validators.pattern(/^[6-9][0-9]{9}$/)]});
  readonly whatsappSameAsMobile = new FormControl(false, {nonNullable: true});
  readonly gender = new FormControl('', {nonNullable: true});

  ngOnInit(): void {
    forkJoin({questionnaire: this.api.getQuestionnaire(), profile: this.api.getProfile(this.sessionId)}).subscribe({
      next: ({questionnaire, profile}) => {
        this.questionnaire.set(questionnaire); this.existingLead.set(profile.leadId !== null); this.locked.set(Boolean(profile.locked));
        if (profile.profile) this.patch(profile.profile);
        this.loading.set(false);
      }, error: (error: Error) => { this.error.set(error.message); this.loading.set(false); },
    });
  }

  requiresStream(): boolean { return this.questionnaire()?.conditional.streamForEducation.includes(this.educationStatus.value) ?? false; }
  requiresCurrentYear(): boolean { return this.questionnaire()?.conditional.currentYearForEducation.includes(this.educationStatus.value) ?? false; }
  valid(): boolean {
    const base = this.name.valid && this.age.valid && this.educationStatus.valid && this.qualification.valid && this.currentSituation.valid && this.email.valid;
    return base && (!this.requiresStream() || Boolean(this.stream.value)) && (!this.requiresCurrentYear() || Boolean(this.currentYear.value)) && (this.qualification.value !== 'OTHER' || Boolean(this.qualificationOther.value.trim())) && (this.whatsappSameAsMobile.value || !this.whatsapp.value || this.whatsapp.valid);
  }

  save(): void {
    if (!this.valid() || this.saving() || this.locked()) { this.touchAll(); return; }
    const profile = this.value();
    const changed = this.changedFields(profile);
    if (this.existingLead() && changed.length && !this.confirmChanges.value) {
      this.error.set('Confirm the changes to the existing CRM profile before saving.'); return;
    }
    this.saving.set(true); this.error.set('');
    this.api.saveProfile(this.sessionId, {...profile, confirmedFields: this.confirmChanges.value ? changed : []}).subscribe({
      next: () => this.router.navigate(['/session', this.sessionId, 'goals']),
      error: (error: Error) => { this.error.set(error.message); this.saving.set(false); },
    });
  }

  private value(): ProspectProfile {
    return {name: this.name.value.trim(), age: this.age.value, educationStatus: this.educationStatus.value || null, qualification: this.qualification.value || null, qualificationOther: this.qualificationOther.value.trim() || null, stream: this.stream.value || null, institution: this.institution.value.trim() || null, currentYear: this.currentYear.value.trim() || null, currentSituation: this.currentSituation.value || null, email: this.email.value.trim() || null, whatsapp: this.whatsapp.value || null, whatsappSameAsMobile: this.whatsappSameAsMobile.value, gender: this.gender.value || null};
  }
  private patch(profile: ProspectProfile): void {
    this.initial = profile; this.name.setValue(profile.name ?? ''); this.age.setValue(profile.age); this.educationStatus.setValue(profile.educationStatus ?? ''); this.qualification.setValue(profile.qualification ?? ''); this.qualificationOther.setValue(profile.qualificationOther ?? ''); this.stream.setValue(profile.stream ?? ''); this.institution.setValue(profile.institution ?? ''); this.currentYear.setValue(profile.currentYear ?? ''); this.currentSituation.setValue(profile.currentSituation ?? ''); this.email.setValue(profile.email ?? ''); this.whatsapp.setValue(profile.whatsapp ?? ''); this.whatsappSameAsMobile.setValue(profile.whatsappSameAsMobile); this.gender.setValue(profile.gender ?? '');
  }
  private changedFields(profile: ProspectProfile): string[] {
    if (!this.initial) return [];
    const fields: (keyof ProspectProfile)[] = ['name', 'age', 'educationStatus', 'stream', 'institution', 'email', 'whatsapp', 'gender'];
    return fields.filter((field) => profile[field] !== this.initial?.[field]);
  }
  private touchAll(): void { [this.name, this.age, this.educationStatus, this.qualification, this.currentSituation, this.email, this.whatsapp].forEach((control) => control.markAsTouched()); }
}
