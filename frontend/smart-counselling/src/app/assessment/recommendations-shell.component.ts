import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { CourseInterest, CourseRecommendation, RecommendationData } from '../core/api.models';
import { SmartCounsellingApiError, SmartCounsellingApiService } from '../core/smart-counselling-api.service';
import { CounsellingStepperComponent } from '../shared/counselling-stepper.component';
import { PageHeaderComponent } from '../shared/page-header.component';
import { CourseInterestControlComponent } from '../courses/course-interest-control.component';

@Component({selector:'sc-recommendations-shell',imports:[RouterLink,CounsellingStepperComponent,PageHeaderComponent,CourseInterestControlComponent],templateUrl:'./recommendations-shell.component.html',changeDetection:ChangeDetectionStrategy.OnPush})
export class RecommendationsShellComponent implements OnInit,OnDestroy {
  private readonly api=inject(SmartCounsellingApiService); private readonly route=inject(ActivatedRoute);
  readonly sessionId=Number(this.route.snapshot.paramMap.get('sessionId')); readonly loading=signal(true); readonly recalculating=signal(false); readonly loadingStep=signal(0); readonly data=signal<RecommendationData|null>(null); readonly error=signal<string|null>(null);
  readonly selected=signal<number[]>([]);readonly interests=signal(new Map<number,CourseInterest>());
  private loadingTimer?:ReturnType<typeof setInterval>;
  readonly loadingMessages=['Finding suitable courses…','Checking education compatibility…','Matching career goals…','Reviewing interests…','Evaluating current skill levels…'];
  ngOnInit():void{this.startLoadingMessages();this.api.getRecommendations(this.sessionId).subscribe({next:(data)=>data.status==='NOT_GENERATED'?this.generate():this.finish(data),error:(error)=>this.fail(error)});}
  ngOnDestroy():void{this.stopLoadingMessages();}
  recalculate():void{this.recalculating.set(true);this.error.set(null);this.generate();}
  review(path:'profile'|'goals'|'skills'):string[]{return ['/session',String(this.sessionId),path];}
  trackCourse(_index:number,item:CourseRecommendation):number{return item.courseId;}
  label(value:string):string{return value.replaceAll('_',' ').toLowerCase().replace(/\b\w/g,(x)=>x.toUpperCase());}
  toggleCompare(courseId:number):void{this.selected.update(items=>items.includes(courseId)?items.filter(x=>x!==courseId):items.length<3?[...items,courseId]:items);}
  selectedForCompare(courseId:number):boolean{return this.selected().includes(courseId);}
  interestFor(courseId:number):CourseInterest{return this.interests().get(courseId)||{courseId,interestLevel:null,primary:false,updatedAt:null};}
  private generate():void{this.api.generateRecommendations(this.sessionId).pipe(finalize(()=>this.recalculating.set(false))).subscribe({next:(data)=>this.finish(data),error:(error)=>this.fail(error)});}
  private finish(data:RecommendationData):void{this.stopLoadingMessages();this.data.set(data);this.loading.set(false);this.api.getCourseInterests(this.sessionId).subscribe({next:x=>this.interests.set(new Map(x.interests.map(item=>[item.courseId,item]))),error:()=>{}});}
  private fail(error:unknown):void{this.stopLoadingMessages();this.loading.set(false);this.error.set(error instanceof SmartCounsellingApiError?error.message:'Recommendations could not be loaded.');}
  private startLoadingMessages():void{this.loadingTimer=setInterval(()=>this.loadingStep.update((value)=>(value+1)%this.loadingMessages.length),700);}
  private stopLoadingMessages():void{if(this.loadingTimer)clearInterval(this.loadingTimer);}
}
