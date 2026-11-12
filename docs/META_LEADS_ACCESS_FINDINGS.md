# Live access findings and remaining test blocker

Review date: 12 November 2026. Production ingestion remains disabled.

## Evidence obtained

- Owner screenshots show app `1626775252463463` published, owned by the intended
  business, with the lead-management use case. This does not establish completed
  App Review, Advanced Access or production eligibility.
- Owner checked both DFA ads and reported form `1806095097277660` on each.
- Using the owner's pinned Secret Manager versions, the read-only check verified
  a valid PAGE token issued to the intended app and resolving to Page
  `300480973645515`. Observed grants include `leads_retrieval`,
  `pages_manage_metadata`, `pages_manage_ads`, `pages_read_engagement` and
  `pages_show_list`. This is a temporary token, not production credential readiness.
- Live form metadata confirms the expected form is ACTIVE and belongs to that Page.
- Both Page `subscribed_apps` and app `subscriptions` returned empty lists in
  successful GET requests. No configured app Page/leadgen callback was returned.
- Owner authorized one native synthetic test lead and attempted creation in Meta's
  testing tool. The tool subsequently reports an existing lead; its visible status
  table contains Zoho Social only, with Pending status and no payload/lead ID.
- The intended app's form `test_leads` registry returned empty on two read-only
  checks. No answer retrieval was attempted because the synthetic guard was not met.

## Conclusions and limits

**Synthetic retrieval gate: BLOCKED.** The native tool's banner does not identify
the lead or prove it is accessible through the intended app. Do not infer success,
creation provenance, duplicate lead count or the reason for the empty registry.
Do not weaken the registry guard, substitute the real-submission `leads` edge,
delete/recreate the existing test, reset Page access or alter third-party CRMs.

**Webhook notification path: NOT CONFIGURED.** App-level and Page-level
subscriptions are separate from answer-retrieval access. Their absence establishes
a notification setup gap; it does not by itself establish why the registry is empty.
Zoho's Pending delivery status is not an ERP test result and is not a gate to repair
on behalf of this integration.

## Concrete next-stage review scope

Before webhook delivery testing, prepare an isolated staging receiver and review
its immutable candidate, HTTPS callback, verification-secret reference, raw-body
signature checks, synthetic-only routing, private audit retention, disable control
and recovery procedure. Keep production enquiry writes and prospect messaging off.
Do not invent a callback URL or use the production ERP URL to unblock Meta setup.
No deployment, app callback registration or Page subscription is authorized by
these findings. Those external changes require a concrete staging review first.

Investigate the native-tool/API discrepancy separately. Preserve the existing
test record and capture any test ID or safe native diagnostic available. If no
supported evidence path can establish its provenance and visibility, report the
blocker for Meta administrator/support review; repeated creation clicks are not
a recovery procedure. Current public testing guides were inaccessible/throttled,
so no unverified claim about app-scoped registry behavior is treated as fact.

## Source and actual effects

Runtime/probe code remains the focused preparation from commit `4c3fd70`.
Its existing 45 focused passes are code-regression evidence, not live retrieval
success. No runtime code changed for these findings; the full suite was not rerun.

The agent performed GET requests only, using credentials in memory. It created
no Meta record, subscription, deployment, ERP record or IAM grant. The owner
performed the Meta permission/consent setup, secret provisioning and native
test-creation attempts described above. Their exact resulting test record is
unresolved. Private evidence is retained outside Git; credentials and raw
lead answers are not included in this review branch.
