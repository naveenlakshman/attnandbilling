import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, map, throwError } from 'rxjs';

import {
  ApiEnvelope, BootstrapData, CounsellingSession, DashboardData,
  AssessmentData, IdentificationData, OtpChallengeSafe, OtpStatusData,
  ProfileData, ProspectProfile, QuestionnaireData, RecommendationData,
  CourseDetailData, SyllabusData, ComparisonData, CourseInterest, InterestLevel,
  CounsellingSummary, OutcomeData, OutcomePayload,
  AnalyticsData, LeadHistoryData, IdentityResolutionData,
} from './api.models';

export class SmartCounsellingApiError extends Error {
  constructor(message: string, readonly code: string, readonly fields: Record<string, string>) {
    super(message);
  }
}

@Injectable({providedIn: 'root'})
export class SmartCounsellingApiService {
  private readonly http = inject(HttpClient);
  private readonly apiBase = '/api/smart-counselling';

  getBootstrap(): Observable<BootstrapData> {
    return this.unwrap(this.http.get<ApiEnvelope<BootstrapData>>(`${this.apiBase}/bootstrap`));
  }

  getDashboard(): Observable<DashboardData> {
    return this.unwrap(this.http.get<ApiEnvelope<DashboardData>>(`${this.apiBase}/dashboard`));
  }

  createSession(branchId?: number | null): Observable<CounsellingSession> {
    const body = branchId ? {branchId} : {};
    return this.unwrapSession(this.http.post<ApiEnvelope<{session: CounsellingSession}>>(`${this.apiBase}/sessions`, body));
  }

  getSession(sessionId: number): Observable<CounsellingSession> {
    return this.unwrapSession(this.http.get<ApiEnvelope<{session: CounsellingSession}>>(`${this.apiBase}/sessions/${sessionId}`));
  }

  listOpenSessions(): Observable<ReadonlyArray<CounsellingSession>> {
    return this.unwrap(this.http.get<ApiEnvelope<{sessions: CounsellingSession[]}>>(`${this.apiBase}/sessions?status=open`))
      .pipe(map((data) => data.sessions));
  }

  resumeSession(sessionId: number): Observable<CounsellingSession> {
    return this.unwrapSession(this.http.post<ApiEnvelope<{session: CounsellingSession}>>(`${this.apiBase}/sessions/${sessionId}/resume`, {}));
  }

  abandonSession(sessionId: number, reason?: string): Observable<CounsellingSession> {
    return this.unwrapSession(this.http.post<ApiEnvelope<{session: CounsellingSession}>>(
      `${this.apiBase}/sessions/${sessionId}/abandon`,
      reason ? {reason} : {},
    ));
  }

  sendOtp(sessionId: number, mobile: string): Observable<OtpChallengeSafe> {
    return this.unwrap(this.http.post<ApiEnvelope<OtpChallengeSafe>>(`${this.apiBase}/sessions/${sessionId}/otp/send`, {mobile}));
  }

  getOtpStatus(sessionId: number): Observable<OtpStatusData> {
    return this.unwrap(this.http.get<ApiEnvelope<OtpStatusData>>(`${this.apiBase}/sessions/${sessionId}/otp/status`));
  }

  verifyOtp(sessionId: number, challengeId: number, otp: string): Observable<IdentificationData> {
    return this.unwrap(this.http.post<ApiEnvelope<IdentificationData>>(`${this.apiBase}/sessions/${sessionId}/otp/verify`, {challengeId, otp}));
  }

  changeMobile(sessionId: number): Observable<{changed: boolean}> {
    return this.unwrap(this.http.post<ApiEnvelope<{changed: boolean}>>(`${this.apiBase}/sessions/${sessionId}/otp/change-mobile`, {}));
  }

  overrideOtp(sessionId: number, mobile: string, reason: string, note?: string): Observable<IdentificationData> {
    return this.unwrap(this.http.post<ApiEnvelope<IdentificationData>>(`${this.apiBase}/sessions/${sessionId}/otp/override`, {mobile, reason, note}));
  }

  getIdentityResolution(sessionId: number): Observable<IdentityResolutionData> {
    return this.unwrap(this.http.get<ApiEnvelope<IdentityResolutionData>>(
      `${this.apiBase}/sessions/${sessionId}/identity-resolution`,
    ));
  }

  confirmIdentityResolution(sessionId: number, leadId: number): Observable<IdentificationData> {
    return this.unwrap(this.http.post<ApiEnvelope<IdentificationData>>(
      `${this.apiBase}/sessions/${sessionId}/identity-resolution`, {leadId},
    ));
  }

  getQuestionnaire(): Observable<QuestionnaireData> {
    return this.unwrap(this.http.get<ApiEnvelope<QuestionnaireData>>(`${this.apiBase}/questionnaire`));
  }

  getProfile(sessionId: number): Observable<ProfileData> {
    return this.unwrap(this.http.get<ApiEnvelope<ProfileData>>(`${this.apiBase}/sessions/${sessionId}/profile`));
  }

  saveProfile(sessionId: number, profile: ProspectProfile & {confirmedFields: string[]}): Observable<ProfileData> {
    return this.unwrap(this.http.put<ApiEnvelope<ProfileData>>(`${this.apiBase}/sessions/${sessionId}/profile`, profile));
  }

  getAssessment(sessionId: number): Observable<AssessmentData> {
    return this.unwrap(this.http.get<ApiEnvelope<AssessmentData>>(`${this.apiBase}/sessions/${sessionId}/assessment`));
  }

  saveAssessment(sessionId: number, answers: Record<string, string | string[]>, complete = false): Observable<AssessmentData> {
    return this.unwrap(this.http.put<ApiEnvelope<AssessmentData>>(`${this.apiBase}/sessions/${sessionId}/assessment`, {answers, complete}));
  }

  getRecommendations(sessionId: number): Observable<RecommendationData> {
    return this.unwrap(this.http.get<ApiEnvelope<RecommendationData>>(`${this.apiBase}/sessions/${sessionId}/recommendations`));
  }

  generateRecommendations(sessionId: number): Observable<RecommendationData> {
    return this.unwrap(this.http.post<ApiEnvelope<RecommendationData>>(`${this.apiBase}/sessions/${sessionId}/recommendations`, {}));
  }

  getCourseDetails(sessionId:number,courseId:number):Observable<CourseDetailData>{return this.unwrap(this.http.get<ApiEnvelope<CourseDetailData>>(`${this.apiBase}/sessions/${sessionId}/courses/${courseId}`));}
  getSyllabus(sessionId:number,courseId:number):Observable<SyllabusData>{return this.unwrap(this.http.get<ApiEnvelope<SyllabusData>>(`${this.apiBase}/sessions/${sessionId}/courses/${courseId}/syllabus`));}
  compareCourses(sessionId:number,courseIds:number[]):Observable<ComparisonData>{return this.unwrap(this.http.get<ApiEnvelope<ComparisonData>>(`${this.apiBase}/sessions/${sessionId}/compare?course_ids=${courseIds.join(',')}`));}
  getCourseInterests(sessionId:number):Observable<{runId:number;interests:CourseInterest[]}>{return this.unwrap(this.http.get<ApiEnvelope<{runId:number;interests:CourseInterest[]}>>(`${this.apiBase}/sessions/${sessionId}/course-interests`));}
  setCourseInterest(sessionId:number,courseId:number,interestLevel:InterestLevel,primary:boolean):Observable<CourseInterest>{return this.unwrap(this.http.put<ApiEnvelope<CourseInterest>>(`${this.apiBase}/sessions/${sessionId}/course-interests/${courseId}`,{interestLevel,primary}));}
  getOutcome(sessionId:number):Observable<OutcomeData>{return this.unwrap(this.http.get<ApiEnvelope<OutcomeData>>(`${this.apiBase}/sessions/${sessionId}/outcome`));}
  saveOutcome(sessionId:number,payload:OutcomePayload):Observable<OutcomeData>{return this.unwrap(this.http.put<ApiEnvelope<OutcomeData>>(`${this.apiBase}/sessions/${sessionId}/outcome`,payload));}
  completeCounselling(sessionId:number,payload:OutcomePayload):Observable<CounsellingSummary>{return this.unwrap(this.http.post<ApiEnvelope<CounsellingSummary>>(`${this.apiBase}/sessions/${sessionId}/complete`,payload));}
  getSummary(sessionId:number):Observable<CounsellingSummary>{return this.unwrap(this.http.get<ApiEnvelope<CounsellingSummary>>(`${this.apiBase}/sessions/${sessionId}/summary`));}
  openAdmissionHandoff(sessionId:number):Observable<{available:boolean;alreadyRegistered:boolean;url?:string;student?:CounsellingSummary['student'];message?:string}>{return this.unwrap(this.http.post<ApiEnvelope<{available:boolean;alreadyRegistered:boolean;url?:string;student?:CounsellingSummary['student'];message?:string}>>(`${this.apiBase}/sessions/${sessionId}/admission-handoff`,{}));}
  getLeadHistory(leadId:number):Observable<LeadHistoryData>{return this.unwrap(this.http.get<ApiEnvelope<LeadHistoryData>>(`${this.apiBase}/leads/${leadId}/history`));}
  getAnalytics(filters:Record<string,string|number|null>={}):Observable<AnalyticsData>{const query=Object.entries(filters).filter(([,v])=>v!==null&&v!=='').map(([k,v])=>`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join('&');return this.unwrap(this.http.get<ApiEnvelope<AnalyticsData>>(`${this.apiBase}/analytics${query?'?'+query:''}`));}

  private unwrapSession(request: Observable<ApiEnvelope<{session: CounsellingSession}>>): Observable<CounsellingSession> {
    return this.unwrap(request).pipe(map((data) => data.session));
  }

  private unwrap<T>(request: Observable<ApiEnvelope<T>>): Observable<T> {
    return request.pipe(
      map((response) => {
        if (!response.success || response.data === null) {
          throw new Error(response.error?.message ?? 'The request could not be completed.');
        }
        return response.data;
      }),
      catchError((error: unknown) => {
        if (error instanceof HttpErrorResponse) {
          const envelope = error.error as ApiEnvelope<unknown> | undefined;
          return throwError(() => new SmartCounsellingApiError(
            envelope?.error?.message ?? 'The request could not be completed.',
            envelope?.error?.code ?? 'request_failed',
            envelope?.error?.fields ?? {},
          ));
        }
        return throwError(() => error);
      }),
    );
  }
}
