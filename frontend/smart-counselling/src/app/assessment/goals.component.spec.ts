import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { of } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { SmartCounsellingApiService } from '../core/smart-counselling-api.service';
import { GoalsComponent } from './goals.component';

describe('GoalsComponent', () => {
  it('resumes goal and multi-select interests from persisted answers', () => { const api = {getQuestionnaire: () => of({}), getAssessment: () => of({profileComplete: true, answers: {primary_goal: 'GET_JOB', interests: ['TALLY', 'EXCEL_DATA'], start_timeframe: 'IMMEDIATELY'}})}; TestBed.configureTestingModule({providers: [{provide: ActivatedRoute, useValue: {snapshot: {paramMap: {get: () => '12'}}}}, {provide: Router, useValue: {navigate: vi.fn()}}, {provide: SmartCounsellingApiService, useValue: api}]}); const item = TestBed.runInInjectionContext(() => new GoalsComponent()); item.ngOnInit(); expect(item.primaryGoal.value).toBe('GET_JOB'); expect(item.interests()).toEqual(['TALLY', 'EXCEL_DATA']); item.toggleInterest('TALLY'); expect(item.interests()).toEqual(['EXCEL_DATA']); });
});
