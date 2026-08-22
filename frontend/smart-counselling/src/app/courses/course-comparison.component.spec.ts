import {TestBed} from '@angular/core/testing';
import {ActivatedRoute} from '@angular/router';
import {describe,expect,it,vi} from 'vitest';
import {SmartCounsellingApiService} from '../core/smart-counselling-api.service';
import {CourseComparisonComponent} from './course-comparison.component';

describe('CourseComparisonComponent',()=>{
  it('requires two or three unique recommended courses before calling the API',()=>{
    const compareCourses=vi.fn();
    TestBed.configureTestingModule({providers:[
      {provide:ActivatedRoute,useValue:{snapshot:{paramMap:{get:()=> '12'},queryParamMap:{get:()=> '4'}}}},
      {provide:SmartCounsellingApiService,useValue:{compareCourses}},
    ]});
    const component=TestBed.runInInjectionContext(()=>new CourseComparisonComponent());
    component.ngOnInit();
    expect(component.error()).toContain('two or three');
    expect(compareCourses).not.toHaveBeenCalled();
  });
});
