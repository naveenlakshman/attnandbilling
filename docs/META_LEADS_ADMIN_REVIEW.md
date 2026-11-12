# Meta leads: administrator setup and review

This is preparation code, not a complete integration. Production ingestion stays
disabled. Follow the steps interactively; inspection does not authorize grants,
secret creation, subscriptions, app-mode changes, lead creation or deployment.

## 1. Inspect the intended app first

Open https://developers.facebook.com/apps/1626775252463463/ while signed in as an
administrator of **Global IT ERP Lead Integration**. Confirm the app header ID,
name, development/live indicator and business association. Start with **Use cases**
if present. Inspect the lead capture/management or Marketing API use-case card and
its **Customize** screen. Labels vary by dashboard version; if no such screen
exists, inspect the sidebar before selecting or adding anything.

The first requested evidence is a cropped screenshot of the app header, mode,
sidebar and use-case cards. Do not reveal an App Secret, token, personal contact
details or prospect data. No credentials screen is needed for this step.

Subsequent evidence, one screen at a time:

- The selected use case and available lead-retrieval capabilities.
- **Permissions and Features** (under App Review or the use case's customization
  screen): permission name, access level, status and outstanding requirements.
  Review `leads_retrieval`, `pages_manage_metadata` and applicable dependencies
  such as `pages_show_list`, `pages_read_engagement`, `pages_manage_ads`,
  `ads_read`/`ads_management` and `business_management`. This is an inspection
  checklist, not a verified requirement that every permission must be requested.
- The app's business verification/review requirements and assigned app roles.
  Do not change mode or request Advanced Access until the actual intended flow
  and requirements are established. Development mode is not production approval.

Current Meta permission and testing guides could not be retrieved during the
audit (HTTP 429). Exact current dependencies, app-mode restrictions and required
review/access levels must be verified from the actual dashboard/current guidance.
Do not infer them from another connector's reporting OAuth grants.

## 2. Verify Page and each ad's form

An authorized administrator must inspect Page access and Leads Access in the
business portfolio. Confirm Page ID `300480973645515`, the business owning the
Page and app, the authorizing user's/system user's assigned assets and any
customized Leads Access/CRM assignment. Record status, not private user details.

In Ads Manager, use account `act_1749366508915125`, campaign
`120254741128620195`. Open each ad separately in its editor, without saving:

| Ad | Creative |
|---|---|
| `120254741578660195` | `2194873687757914` |
| `120254741568380195` | `1093424900345572` |

Inspect the Identity/Page and Instant Form selection. View the selected form's
details/preview and record exact form ID, name and status. Cross-check it in the
Page's Instant Forms library (the Meta Business Suite location may vary).
Screenshots should show configuration only, never submitted answers or lead lists.
Treat `1806095097277660` as provisional until it matches the actual selections.
Two different forms require two reviewed mappings. A conversion tracking ID,
similar name or Page membership alone does not prove an ad/form association.

## 3. Provision credentials only after the inspection is reviewed

Proposed Google Cloud project: `global-it-edu-app`. Proposed secret IDs:

| Secret ID | Purpose |
|---|---|
| `meta-erp-leads-staging-page-token` | Intended app's authorized Page token |
| `meta-erp-leads-app-secret` | Existing intended app's App Secret |
| `meta-erp-leads-staging-webhook-verify-token` | Independently generated random callback challenge secret; not yet needed by the GET-only probe |

These are proposals, not existing resources. A separate staging app/Page is
preferable where available; do not use a token for a different app as access proof.

Administrator prerequisites/actions, before any change:

1. Confirm project, staging-only purpose, identity running the verifier, approved
   storage/replication policy, and permission to create secrets and grant IAM.
   If Secret Manager API is disabled, an authorized Service Usage administrator
   must enable it. Do not alter service configuration to enable ingestion.
2. A cloud administrator creates the named secrets with appropriate permissions.
   Google documents Secret Manager Admin for creation; a narrower custom role
   can be used. Grant a credential custodian Secret Version Adder on existing
   secrets when only uploading versions is required. Do not grant secret admin
   privileges to the verifier or application.
3. An authorized Meta administrator obtains a Page token through the approved
   flow for this exact App ID and Page. Verify required app role, Page/Leads
   Access and consented grants first. If using Graph API Explorer for the test
   flow, confirm the selected app is this app, not Explorer's own app. Record
   token provenance and expiry policy; do not assume a token never expires.
   Obtain the existing App Secret without resetting it or disrupting other users.
4. In the authenticated Google Cloud Console, open Secret Manager, confirm the
   project/name, and create a version using the secure secret-value field.
   Never place values in chat, Git, screenshots, environment example files,
   shell arguments, shell history or saved transcripts. Do not use a downloaded
   service-account key. Prefer the console procedure over ad hoc token commands.
5. Give the approved verifier identity `roles/secretmanager.secretAccessor` on
   the two required secrets only. Future webhook/worker identities receive only
   the secrets each needs, after their own approval. Metadata Viewer is optional
   for diagnostics; it does not allow reading payloads. IAM policy changes need
   a principal permitted to set the relevant secret's policy.
6. Return **references only**, pinned to numeric versions, for example
   `projects/global-it-edu-app/secrets/meta-erp-leads-staging-page-token/versions/1`.
   The actual version may differ. The probe rejects `latest`. Record rotation,
   revocation and expiry ownership. No production service is attached to these
   secrets during this setup.

Google references:
https://cloud.google.com/secret-manager/docs/creating-and-accessing-secrets
and https://cloud.google.com/secret-manager/docs/access-control .

## 4. Synthetic test proposal: approval required before Meta writes

After Page/form/app access, numeric secret references and a supported Graph
version are verified, propose one explicitly synthetic test on the confirmed
form. Confirm existing CRM integrations cannot message a real person from that
test. Use native synthetic fields or approved staff-controlled contact details;
never a prospect's contact details. Inspect any existing test slot first. Do not
delete an existing test lead without separate approval.

The administrator checks the supported testing procedure for the app's current
mode and role. If blocked, report the exact safe error/status; do not switch the
app live, broaden grants or create a real prospect submission to bypass it.
Approve test-lead creation separately from the read-only retrieval. No webhook
subscription or receiver deployment is part of this test.

After approval, the authorized administrator creates/identifies the synthetic lead
and supplies its ID. Run `scripts/verify_meta_lead_access.py` with the pinned
Graph version, intended App ID, verified Page/form IDs, test ID, two numeric secret
references and a private evidence path **outside the repository**. It verifies:

- Token valid and issued to the intended app; Page token resolves to that Page.
- Form belongs to Page; supplied lead is registered on that form's `test_leads`.
- Single test lead can be retrieved with expected answer fields and timestamps.
- Existing Page/app `leadgen` subscription state, without changing it.

The probe uses GET only, stores safe field names/counts/hash, and never imports an
enquiry. App review status and each ad/form association still need separate proof.
An empty subscription is an expected missing setup item at this phase, not
permission to install the app. No live retrieval has been demonstrated by stub
tests. Production ingestion remains off until all results are reviewed.

Official endpoint-check specification:
https://github.com/facebookincubator/catalogue-of-api-solutions/blob/main/solutions/leads/leads-retrieval-set-up-checker.md

## Course-hours decision

The approved campaign specification is **225 hours**, 18 November 2026 to
10 April 2027, 12:00-14:00 Asia/Kolkata. The discrepant 180-hour figure comes
from the existing course catalogue field `courses.duration_hours`, not a
calculation from the campaign's dates or batch schedule. The course form accepts
this field directly and course create/edit persists it. Course intelligence also
reads it. The available audit does not preserve field-level before/after values;
it cannot explain who selected 180 or whether 225 is a new course version or
bundle. Obtain the approved syllabus/contact-hour plan and catalogue owner decision.

Do not change a course or select/create a batch automatically. In particular,
the existing course editor can also populate blank certificate-duration snapshots;
an hour correction needs a separately scoped review. No course or batch record
is changed by this preparation.

## Review branch scope

The review branch contains the focused manual enquiry/tenant patch, read-only
access probe, synthetic tests and minimal MySQL test-fixture support, plus this
guide. It excludes production snapshots, reconciliation evidence, lead answers,
financial correction documents, credentials and the private evidence directory.

This is not a receiver/worker implementation. Shared intake, durable submissions,
deduplication, pending tasks, retries, reconciliation and operational switches
remain future gated work. Imports must remain New Lead, with no completed contact,
automatic enrolment, attribution/history overwrite or prospect messaging.

Prepared branch: `codex/meta-leads-review`, based on public `origin/main` commit
`b50fe4f4d468f5e7a8bd5ea88a1157b306c8fe08`. Original preparation commit
`a89daacc4a31afa41eeaa258f59fcb33f0a225f8` remains on the separate local
`codex/meta-leads-preparation` branch. This review branch copies only its focused
source/tests and MySQL fixture support, normalizing line endings; it does not
include that commit's unpublished financial-release ancestors.

Review-branch verification: **45 focused checks passed**, zero failures/skips,
including disposable Oracle MySQL 8.0.45 and SQLite manual-enquiry/tenant checks,
plus stubbed access-probe safety tests. The full suite was not rerun on this
separate baseline. Earlier full-suite results belong to the original preparation
revision and do not certify this branch. These checks do not demonstrate real
Meta access. No publication, merge or deployment is part of this preparation.
