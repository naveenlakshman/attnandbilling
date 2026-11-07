import {TestBed} from '@angular/core/testing';
import {of} from 'rxjs';
import {describe,expect,it,vi} from 'vitest';
import {SmartCounsellingApiService} from '../core/smart-counselling-api.service';
import {CourseInterestControlComponent} from './course-interest-control.component';

describe('CourseInterestControlComponent',()=>{
  it('persists and reflects a primary interest',()=>{
    const setCourseInterest=vi.fn(()=>of({courseId:8,interestLevel:'HIGHLY_INTERESTED' as const,primary:true,updatedAt:'now'}));
    TestBed.configureTestingModule({providers:[{provide:SmartCounsellingApiService,useValue:{setCourseInterest}}]});
    const component=TestBed.runInInjectionContext(()=>new CourseInterestControlComponent());
    component.sessionId=12; component.courseId=8;
    component.save('HIGHLY_INTERESTED',true);
    expect(setCourseInterest).toHaveBeenCalledWith(12,8,'HIGHLY_INTERESTED',true);
    expect(component.primary()).toBe(true);
    expect(component.message()).toBe('Interest saved.');
  });
});
