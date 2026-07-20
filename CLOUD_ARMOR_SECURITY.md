# Cloud Armor security policy

Production load balancer backend: `erp-cloudrun-backend`

Policy: `default-security-policy-for-erp-cloudrun-backend`

## Design

Cloud Armor inspects anonymous and public traffic. Authenticated application
namespaces allow POST requests through to Flask because Flask provides the
controls that understand application identity and form semantics:

- signed session cookies;
- staff/student login decorators and role checks;
- global Flask-WTF CSRF validation;
- per-form replay tokens where implemented;
- file type and size validation;
- rich-text allow-list sanitization;
- database parameter binding.

The authenticated namespace rules do not make the endpoints public. Requests
without a valid signed session and CSRF token are rejected by Flask.

## Active rule order

| Priority | Action | Scope |
| --- | --- | --- |
| 880 | Allow | POST under `/assets/`, `/attendance/`, `/baddebt/`, `/billing/`, `/leads/` |
| 881 | Allow | POST under `/lms_admin/`, `/reports/`, `/users/`, `/branches/`, `/admin/`, `/company-profile` |
| 882 | Allow | POST under `/student/`, excluding `/student/login` |
| 1000 | Preview deny | Cloud Armor SQLi stable ruleset |
| 1001 | Deny 403 | Cloud Armor XSS stable ruleset |
| 1002 | Deny 403 | Cloud Armor LFI stable ruleset |
| 1003 | Deny 403 | Cloud Armor RCE stable ruleset |
| 2147483646 | Throttle | 500 requests per source IP per 60 seconds |
| 2147483647 | Allow | Default traffic not matched above |

Public POST endpoints such as `/login`, `/student/login`, `/enquire`, public
exam submission endpoints, and `/api/...` do not match priorities 880-882 and
therefore retain full Cloud Armor WAF inspection.

## Logging and diagnosis

Load-balancer logging is enabled at a 100% sample rate. Inspect recent denials:

```powershell
gcloud logging read `
  'resource.type="http_load_balancer" AND httpRequest.status=403' `
  --project=global-it-edu-app `
  --freshness=30m `
  --limit=50 `
  --format=json
```

Important fields are:

- `jsonPayload.enforcedSecurityPolicy.priority`
- `jsonPayload.enforcedSecurityPolicy.preconfiguredExprIds`
- `jsonPayload.statusDetails`

Do not add one-off WAF exclusions before confirming the enforced priority and
signature in these logs. Add new authenticated namespaces only when the Flask
route has session authorization and CSRF protection.

## Verification expectations

An unauthenticated probe sent to an authenticated namespace should pass Cloud
Armor but be rejected by Flask with a redirect or CSRF 400. An attack-shaped
probe sent to a public endpoint should be denied by Cloud Armor with 403.

The production validation performed on 2026-07-20 confirmed:

- priority 880 accepted an Assets POST and Flask rejected the invalid form;
- priority 881 accepted an LMS POST and Flask rejected the invalid form;
- priority 882 accepted a student-portal POST and Flask rejected the invalid form;
- XSS-shaped POSTs to `/login` and `/enquire` were denied at priority 1001.
