# Smart Counselling Phase 1

Smart Counselling is an isolated standalone Angular workspace mounted inside the
existing Flask/Jinja ERP shell. Flask owns staff authentication, tenant context,
subscription feature access, the host route, and JSON APIs.

## Routes

- `/smart-counselling` - Angular dashboard
- `/smart-counselling/start` - first-step mobile verification shell
- `/api/smart-counselling/bootstrap` - active institute and staff DTO
- `/api/smart-counselling/dashboard` - tenant-scoped Phase 1 dashboard DTO

Angular fallback routes are served by the Flask blueprint. API routes are kept
outside that fallback namespace.

## Development

Use Node 20.19+, 22.12+, or 24 as supported by Angular 21.

```powershell
cd frontend/smart-counselling
pnpm install --frozen-lockfile
pnpm watch
```

Run Flask normally in a second terminal. The watch build writes browser assets
to `static/smart-counselling/browser`, so requests remain same-origin and use
the existing Flask session and CSRF meta tag.

## Production

`pnpm build` produces optimized assets under
`static/smart-counselling/browser`. The Dockerfile has a Node build stage and
copies only those assets into the final unprivileged Python image. Existing
Cloud Build files already build the repository Dockerfile, so no separate
frontend deployment is introduced.

The Angular HTTP interceptor reads the existing `csrf-token` meta element and
sends `X-CSRFToken` for state-changing requests. No API credentials, domains,
staff credentials, or authentication tokens are stored in Angular.

## Feature rollout

The blueprint uses the existing subscription feature key `smart_counselling`.
Navigation is hidden and requests are denied until the active institute's plan
or feature override explicitly enables that key. No database migration is part
of Phase 1.
