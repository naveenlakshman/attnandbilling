import {KeyValuePipe} from '@angular/common';
import {ChangeDetectionStrategy,Component,OnInit,inject,signal} from '@angular/core';
import {ActivatedRoute,RouterLink} from '@angular/router';
import {LeadHistoryData} from '../core/api.models';
import {SmartCounsellingApiError,SmartCounsellingApiService} from '../core/smart-counselling-api.service';
import {PageHeaderComponent} from '../shared/page-header.component';

@Component({selector:'sc-history',imports:[RouterLink,PageHeaderComponent,KeyValuePipe],templateUrl:'./history.component.html',changeDetection:ChangeDetectionStrategy.OnPush})
export class HistoryComponent implements OnInit {
  private api=inject(SmartCounsellingApiService); private route=inject(ActivatedRoute);
  readonly leadId=Number(this.route.snapshot.paramMap.get('leadId')); readonly data=signal<LeadHistoryData|null>(null);
  readonly loading=signal(true); readonly error=signal(''); readonly expanded=signal(new Set<number>());
  ngOnInit(){this.api.getLeadHistory(this.leadId).subscribe({next:x=>{this.data.set(x);if(x.sessions[0])this.expanded.set(new Set([x.sessions[0].id]));this.loading.set(false);},error:e=>{this.error.set(e instanceof SmartCounsellingApiError?e.message:'Counselling history could not be loaded.');this.loading.set(false);}});}
  toggle(id:number){this.expanded.update(old=>{const next=new Set(old);next.has(id)?next.delete(id):next.add(id);return next;});}
  isExpanded(id:number){return this.expanded().has(id);}
  label(value:string|null|undefined){return(value||'—').replaceAll('_',' ').toLowerCase().replace(/\b\w/g,c=>c.toUpperCase());}
  answer(value:string|string[]|undefined){return Array.isArray(value)?value.map(x=>this.label(x)).join(', '):this.label(value);}
}
