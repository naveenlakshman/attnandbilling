import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { of } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { SmartCounsellingApiService } from '../core/smart-counselling-api.service';
import { SkillsComponent } from './skills.component';

describe('SkillsComponent', () => {
  it('activates programming experience only for the persisted programming interest', () => { const api = {getQuestionnaire: () => of({}), getAssessment: () => of({profileComplete: true, answers: {primary_goal: 'GET_JOB', interests: ['PROGRAMMING'], computer_skill: 'BASIC'}})}; TestBed.configureTestingModule({providers: [{provide: ActivatedRoute, useValue: {snapshot: {paramMap: {get: () => '12'}}}}, {provide: Router, useValue: {navigate: vi.fn()}}, {provide: SmartCounsellingApiService, useValue: api}]}); const item = TestBed.runInInjectionContext(() => new SkillsComponent()); item.ngOnInit(); expect(item.programmingSelected()).toBe(true); expect(item.computer.value).toBe('BASIC'); });
});
