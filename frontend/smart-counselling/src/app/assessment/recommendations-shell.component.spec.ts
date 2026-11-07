import { TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { SmartCounsellingApiService } from '../core/smart-counselling-api.service';
import { RecommendationsShellComponent } from './recommendations-shell.component';

const result={run:{id:4,engineVersion:'SMART_COUNSELLING_ENGINE_V1',assessmentVersion:'SMART_COUNSELLING_V1',createdAt:'2026-08-22'},status:'MATCHES_FOUND' as const,recommendations:[{courseId:1,courseName:'DFA',courseCategory:'Diploma',rank:1,score:94,matchLabel:'EXCELLENT_MATCH' as const,eligibilityStatus:'ELIGIBLE' as const,whyRecommended:['Aligned with your goal.'],considerations:[],skillChips:['ACCOUNTING'],bestMatch:true,actions:{courseDetails:'PHASE_7' as const,syllabus:'PHASE_7' as const,comparison:'PHASE_7' as const}}],otherSuitableCourses:[],decisionSupportNote:'Decision support only.'};

describe('RecommendationsShellComponent',()=>{
  function subject(api:Record<string,unknown>){TestBed.configureTestingModule({providers:[{provide:ActivatedRoute,useValue:{snapshot:{paramMap:{get:()=> '12'}}}},{provide:SmartCounsellingApiService,useValue:{getCourseInterests:()=>of({runId:4,interests:[]}),...api}}]});return TestBed.runInInjectionContext(()=>new RecommendationsShellComponent());}
  it('reloads an existing persisted recommendation run without recalculating',()=>{const generate=vi.fn(()=>of(result));const item=subject({getRecommendations:()=>of(result),generateRecommendations:generate});item.ngOnInit();expect(item.data()?.recommendations[0].courseName).toBe('DFA');expect(generate).not.toHaveBeenCalled();item.ngOnDestroy();});
  it('generates when no current run exists',()=>{const generate=vi.fn(()=>of(result));const item=subject({getRecommendations:()=>of({run:null,status:'NOT_GENERATED',recommendations:[],otherSuitableCourses:[],decisionSupportNote:''}),generateRecommendations:generate});item.ngOnInit();expect(generate).toHaveBeenCalledWith(12);expect(item.data()?.status).toBe('MATCHES_FOUND');item.ngOnDestroy();});
});
