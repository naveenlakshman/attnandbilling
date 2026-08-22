import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    title: 'Smart Counselling',
    loadComponent: () => import('./dashboard/dashboard.component').then((m) => m.DashboardComponent),
  },
  {
    path: 'start',
    title: 'Starting Counselling',
    loadComponent: () => import('./start/session-starter.component').then((m) => m.SessionStarterComponent),
  },
  {
    path: 'session/:sessionId/verify',
    title: 'Verify Prospect',
    loadComponent: () => import('./verify/verify-session.component').then((m) => m.VerifySessionComponent),
  },
  {
    path: 'session/:sessionId/profile',
    title: 'Prospect Profile',
    loadComponent: () => import('./profile/profile.component').then((m) => m.ProfileComponent),
  },
  {
    path: 'session/:sessionId/goals',
    title: 'Goals and Interests',
    loadComponent: () => import('./assessment/goals.component').then((m) => m.GoalsComponent),
  },
  {
    path: 'session/:sessionId/skills',
    title: 'Skills Assessment',
    loadComponent: () => import('./assessment/skills.component').then((m) => m.SkillsComponent),
  },
  {
    path: 'session/:sessionId/recommendations',
    title: 'Course Recommendations',
    loadComponent: () => import('./assessment/recommendations-shell.component').then((m) => m.RecommendationsShellComponent),
  },
  {path:'session/:sessionId/course/:courseId',title:'Course Details',loadComponent:()=>import('./courses/course-detail.component').then((m)=>m.CourseDetailComponent)},
  {path:'session/:sessionId/compare',title:'Compare Courses',loadComponent:()=>import('./courses/course-comparison.component').then((m)=>m.CourseComparisonComponent)},
  {path:'session/:sessionId/outcome',title:'Counselling Outcome',loadComponent:()=>import('./outcome/outcome.component').then((m)=>m.OutcomeComponent)},
  {path:'history/:leadId',title:'Counselling History',loadComponent:()=>import('./insights/history.component').then((m)=>m.HistoryComponent)},
  {path:'analytics',title:'Smart Counselling Analytics',loadComponent:()=>import('./insights/analytics.component').then((m)=>m.AnalyticsComponent)},
  {path: '**', redirectTo: ''},
];
