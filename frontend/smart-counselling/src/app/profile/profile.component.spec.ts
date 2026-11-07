import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { of } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { SmartCounsellingApiService } from '../core/smart-counselling-api.service';
import { ProfileComponent } from './profile.component';

const questionnaire = {assessmentVersion: 'SMART_COUNSELLING_V1', profile: {educationStatus: [], qualification: [], stream: [], currentSituation: [], gender: []}, careerGoals: [], interests: [], skills: {knowledge: [], english: [], programming: []}, startTimeframes: [], preferences: {durations: [], timings: [], learningModes: [], languages: []}, conditional: {programmingExperienceWhenInterest: 'PROGRAMMING', currentYearForEducation: ['DEGREE'], streamForEducation: ['DEGREE']}};

describe('ProfileComponent', () => {
  function subject(profile: any = null) {
    const api = {getQuestionnaire: () => of(questionnaire), getProfile: () => of({leadId: profile ? 5 : null, profile, profileComplete: Boolean(profile), nextStep: 'PROFILE'})};
    TestBed.configureTestingModule({providers: [{provide: ActivatedRoute, useValue: {snapshot: {paramMap: {get: () => '12'}}}}, {provide: Router, useValue: {navigate: vi.fn()}}, {provide: SmartCounsellingApiService, useValue: api}]});
    return TestBed.runInInjectionContext(() => new ProfileComponent());
  }
  it('requires conditional stream and current year for degree education', () => { const item = subject(); item.questionnaire.set(questionnaire); item.name.setValue('Kiran Kumar'); item.age.setValue(21); item.educationStatus.setValue('DEGREE'); item.qualification.setValue('BCOM'); item.currentSituation.setValue('STUDENT'); expect(item.valid()).toBe(false); item.stream.setValue('COMMERCE'); item.currentYear.setValue('2'); expect(item.valid()).toBe(true); });
  it('resumes an existing lead profile from the API', () => { const profile = {name: 'Existing Kiran', age: 22, educationStatus: 'DEGREE', qualification: 'BCOM', qualificationOther: null, stream: 'COMMERCE', institution: null, currentYear: '2', currentSituation: 'STUDENT', email: null, whatsapp: null, whatsappSameAsMobile: false, gender: null}; const item = subject(profile); item.ngOnInit(); expect(item.existingLead()).toBe(true); expect(item.name.value).toBe('Existing Kiran'); });
});
