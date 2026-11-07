export interface ApiError {
  code: string;
  message: string;
  fields: Record<string, string>;
}

export interface ApiEnvelope<T> {
  success: boolean;
  data: T | null;
  error: ApiError | null;
}

export interface BootstrapData {
  apiVersion: string;
  modulePhase: number;
  tenant: {id: number; name: string; shortName: string; primaryColor: string};
  staff: {
    id: number;
    name: string;
    role: 'admin' | 'staff';
    branchId: number | null;
    canViewAllBranches: boolean;
  };
  activeBranches: ReadonlyArray<{id: number; name: string}>;
  navigation: {dashboard: string; start: string};
  csrf: {headerName: string};
  otp: {length: number; overrideReasons: string[]; canOverride: boolean};
}

export interface DashboardData {
  asOfDate: string;
  metrics: {
    todaySessions: number;
    newUnlinkedSessions: number;
    completedSessions: number;
    openSessions: number;
    readyForAdmission: number | null;
  };
  recentSessions: ReadonlyArray<DashboardSession>;
  availability: Record<string, string>;
}

export type CounsellingSessionStatus =
  | 'STARTED'
  | 'IDENTIFICATION_PENDING'
  | 'IDENTIFIED'
  | 'IN_PROGRESS'
  | 'OUTCOME_PENDING'
  | 'COMPLETED'
  | 'ABANDONED';

export interface CounsellingSession {
  id: number;
  status: CounsellingSessionStatus;
  branch: {id: number; name: string};
  counsellor: {id: number; name: string};
  prospect: {id: number; name: string} | null;
  mobileVerified: boolean;
  verificationMethod: string | null;
  mobileMasked: string | null;
  identityMobileMasked: string | null;
  identificationStatus: ProspectStatus | null;
  startedAt: string;
  completedAt: string | null;
  abandonedAt: string | null;
  updatedAt: string;
  canResume: boolean;
}

export type DashboardSession = Pick<
  CounsellingSession,
  'id' | 'status' | 'branch' | 'counsellor' | 'prospect' | 'startedAt' | 'updatedAt' | 'canResume'
>;

export type ProspectStatus =
  | 'NEW' | 'EXISTING_LEAD' | 'EXISTING_LEAD_RESTRICTED' | 'MULTIPLE_MATCHES'
  | 'EXISTING_STUDENT' | 'SOFT_DELETED_MATCH'
  | 'UNVERIFIED_MATCH_REQUIRES_CONFIRMATION' | 'UNVERIFIED_NEW';

export interface OtpChallengeSafe {
  challengeId: number;
  mobileMasked: string;
  expiresInSeconds: number;
  resendAvailableInSeconds: number;
}

export interface OtpStatusData {
  sessionStatus: CounsellingSessionStatus;
  activeChallenge: OtpChallengeSafe | null;
}

export interface LeadSummary {
  id: number;
  name: string;
  mobileMasked: string;
  stage: string | null;
  branch?: string | null;
  assignedCounsellor?: string | null;
  createdAt?: string | null;
  studentCode?: string | null;
}

export interface IdentificationData {
  verification: {verified: boolean; method: 'OTP' | 'OVERRIDE'; mobileMasked: string};
  prospect: {status: ProspectStatus; lead: LeadSummary | null; matches: LeadSummary[]};
  nextStep: 'PROFILE' | 'RESOLUTION';
}

export interface IdentityResolutionData {
  sessionId: number;
  mobileMasked: string;
  candidates: ReadonlyArray<LeadSummary & {
    status: string | null;
    archived: boolean;
    viewUrl: string;
  }>;
}

export interface OptionItem {code: string; label: string}

export interface QuestionnaireData {
  assessmentVersion: string;
  profile: Record<string, OptionItem[]>;
  careerGoals: OptionItem[];
  interests: OptionItem[];
  skills: {knowledge: OptionItem[]; english: OptionItem[]; programming: OptionItem[]};
  startTimeframes: OptionItem[];
  preferences: {durations: OptionItem[]; timings: OptionItem[]; learningModes: OptionItem[]; languages: OptionItem[]};
  conditional: {programmingExperienceWhenInterest: string; currentYearForEducation: string[]; streamForEducation: string[]};
}

export interface ProspectProfile {
  name: string; age: number | null; educationStatus: string | null; qualification: string | null;
  qualificationOther: string | null; stream: string | null; institution: string | null;
  currentYear: string | null; currentSituation: string | null; email: string | null;
  whatsapp: string | null; whatsappSameAsMobile: boolean; gender: string | null;
}

export interface ProfileData {
  leadId: number | null; profile: ProspectProfile | null; profileComplete: boolean;
  assessmentComplete?: boolean; nextStep: 'PROFILE' | 'GOALS' | 'SKILLS' | 'RECOMMENDATIONS';
  locked?: boolean; created?: boolean;
}

export interface AssessmentData {
  assessment: {id: number; version: string; status: 'IN_PROGRESS' | 'COMPLETED'} | null;
  answers: Record<string, string | string[]>; profileComplete: boolean; assessmentComplete: boolean;
  nextStep: 'PROFILE' | 'GOALS' | 'SKILLS' | 'RECOMMENDATIONS';
}

export interface CourseRecommendation {
  courseId: number; courseName: string; courseCategory: string | null; rank: number;
  score: number; matchLabel: 'EXCELLENT_MATCH'|'STRONG_MATCH'|'GOOD_MATCH'|'POSSIBLE_MATCH'|'LOW_MATCH';
  eligibilityStatus: 'ELIGIBLE'; whyRecommended: string[]; considerations: string[];
  skillChips: string[]; bestMatch: boolean;
  actions: {courseDetails: 'PHASE_7'; syllabus: 'PHASE_7'; comparison: 'PHASE_7'};
}

export interface RecommendationData {
  run: {id: number; engineVersion: string; assessmentVersion: string; createdAt: string} | null;
  status: 'NOT_GENERATED'|'MATCHES_FOUND'|'NO_STRONG_MATCH';
  recommendations: CourseRecommendation[]; otherSuitableCourses: CourseRecommendation[];
  decisionSupportNote: string;
}

export type InterestLevel='INTERESTED'|'HIGHLY_INTERESTED'|'NOT_INTERESTED';
export interface CourseInterest {courseId:number;interestLevel:InterestLevel|null;primary:boolean;updatedAt:string|null}
export interface SyllabusData {status:'AVAILABLE'|'NOT_AVAILABLE';message:string|null;program:{id:number;title:string}|null;chapters:{id:number;title:string;order:number;topics:{id:number;title:string;order:number;estimatedTime:number|null}[]}[]}
export interface CourseDetailData {
  course:{id:number;name:string;domain:string|null;category:string|null;fee:number;duration:string|null;hours:number|null;active:boolean;availability:'AVAILABLE'|'CURRENTLY_UNAVAILABLE'};
  recommendation:{runId:number;rank:number|null;score:number|null;matchLabel:string|null;eligibilityStatus:string;whyRecommended:string[];considerations:string[]};
  intelligence:{purpose:string|null;shortDescription:string|null;detailedDescription:string|null;targetAudience:string|null;minimumEducation:string|null;preferredBackground:string|null;hardEligibility:string|null;startingSkillLevel:string|null;certification:{title:string|null;issuingBody:string|null;included:boolean;externalExamRequired:boolean;details:string|null};prerequisites:{skill_dimension:string;minimum_level:string}[];skillsTaught:string[];learningOutcomes:string[];careerOutcomes:string[];jobRoles:string[]};
  syllabus:SyllabusData|{status:'AVAILABLE'|'NOT_AVAILABLE'};batches:{id:number;name:string;branch:string;startDate:string|null;endDate:string|null;startTime:string|null;endTime:string|null;status:string}[];interest:CourseInterest;
}
export interface ComparisonData {runId:number;courses:CourseDetailData[]}
export interface OutcomePolicy {code:string;label:string;requiresPrimary:boolean;requiresInterestedCourse:boolean;requiresFollowup:boolean;nextActions:{code:string;label:string}[];reasons:{code:string;label:string}[]}
export interface CounsellingSummary {
  sessionId:number;status:string;completedAt:string|null;prospect:{id:number;name:string;verificationStatus:string;qualification:string|null;primaryGoal:string|null;viewUrl:string};
  topRecommendation:{courseId:number;courseName:string;score:number;matchLabel:string}|null;primaryInterest:(CourseInterest&{courseName:string})|null;otherInterests:(CourseInterest&{courseName:string})[];
  outcome:string|null;outcomeReason:string|null;nextAction:string|null;nextFollowupDate:string|null;staffNotes:string|null;counsellor:{id:number;name:string};followupId:number|null;
  admissionHandoffAvailable:boolean;admissionUrl:string;alreadyRegistered:boolean;student:{id:number;studentCode:string;name:string;viewUrl:string}|null;
}
export interface OutcomeData {policies:OutcomePolicy[];current:{outcome:string|null;outcomeReason:string|null;nextAction:string|null;nextFollowupDate:string|null;staffNotes:string|null};interests:(CourseInterest&{courseName:string})[];primaryInterest:(CourseInterest&{courseName:string})|null;validation:{valid:boolean;missing:string[]};summary:CounsellingSummary}
export interface OutcomePayload {outcome:string;outcomeReason:string|null;nextAction:string;nextFollowupDate:string|null;staffNotes:string|null}
export interface HistoryRecommendation {courseId:number;courseName:string;rank:number;score:number;matchLabel:string;whyRecommended:string[];considerations:string[]}
export interface HistoryRun {id:number;engineVersion:string;assessmentVersion:string;createdAt:string;completedAt:string;outcomeStatus:string;recommendations:HistoryRecommendation[]}
export interface HistorySession {id:number;status:string;startedAt:string;completedAt:string|null;abandonedAt:string|null;counsellor:{id:number;name:string};branch:{id:number;name:string};verificationStatus:string;assessment:{status:string|null;version:string|null;answers:Record<string,string|string[]>};recommendationRuns:HistoryRun[];finalRecommendationRun:HistoryRun|null;interests:(CourseInterest&{courseName:string})[];primaryInterest:(CourseInterest&{courseName:string})|null;outcome:{code:string|null;reason:string|null;nextAction:string|null;nextFollowupDate:string|null;staffNotes:string|null};activities:{type:string;label:string;at:string}[]}
export interface LeadHistoryData {lead:{id:number;name:string};currentCrm:{ownerId:number|null;stage:string|null;status:string|null;nextFollowupDate:string|null;student:{id:number;studentCode:string;name:string;viewUrl:string}|null};sessions:HistorySession[]}
export interface AnalyticsData {asOf:string;filters:{dateFrom:string;dateTo:string;branchId:number|null;counsellorId:number|null;recommendedCourseId:number|null;primaryCourseId:number|null};filterOptions:{branches:{id:number;name:string}[];counsellors:{id:number;name:string;branchId:number|null}[];courses:{id:number;name:string}[]};overview:Record<string,number>;funnel:{code:string;label:string;count:number;unit:string}[];outcomes:{code:string;count:number}[];courses:{recommended:{courseId:number;courseName:string;count:number}[];primarySelected:{courseId:number;courseName:string;count:number}[];alignment:{matchedTop:number;differentChoice:number;noPrimaryChoice:number}};noSuitableCourse:{count:number;dimensions:{dimension:string;value:string;count:number}[]};counsellors:{id:number;name:string;sessions:number;completed:number;completionRate:number;readyForAdmission:number;followupsCreated:number}[];followups:{total:number;dueToday:number;overdue:number;upcoming:number};definitions:Record<string,string>}
