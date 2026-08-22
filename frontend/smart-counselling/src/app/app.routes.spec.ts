import { describe, expect, it } from 'vitest';

import { routes } from './app.routes';

describe('Smart Counselling routes', () => {
  it('exposes the dashboard, starter, and refresh-safe session verification routes', () => {
    expect(routes.map((route) => route.path)).toEqual([
      '', 'start', 'session/:sessionId/verify', 'session/:sessionId/profile',
      'session/:sessionId/goals', 'session/:sessionId/skills',
      'session/:sessionId/recommendations', 'session/:sessionId/course/:courseId',
      'session/:sessionId/compare', 'session/:sessionId/outcome', 'history/:leadId',
      'analytics', '**',
    ]);
  });
});
