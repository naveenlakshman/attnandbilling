# Cashfree sandbox fee collection

The Flask billing blueprint exposes Cashfree checkout on **Bill of Supply / invoice detail**.
Signed student payment links and reminder integration are described in
[Student payment links](CASHFREE_STUDENT_PAYMENT_LINKS.md).
It uses the existing invoice, receipt, installment, tenant receipt-number sequence, and activity-log tables.
Sandbox receipts are labelled `SANDBOX Cashfree` in their notes. Use an ERP test database:
simulated payments update that database's fee ledger.

## Configuration

The root `.env` is already loaded by `config.py`. These settings are server-only:

```dotenv
CASHFREE_APP_ID=<your sandbox app ID>
CASHFREE_SECRET_KEY=<your complete sandbox secret>
CASHFREE_API_URL=https://sandbox.cashfree.com/pg
CASHFREE_INSTITUTE_ID=1
CASHFREE_NOTIFY_URL=https://<verified-tenant-host>/billing/cashfree/webhook
```

The three requested `.env` entries were added only if missing. The supplied secret is
masked; replace it locally with the complete sandbox secret. Do not commit `.env`.
Restart the Flask process after changing environment settings.

`CASHFREE_INSTITUTE_ID` defaults to `1`. Set it to the institute receiving payments:
this integration binds one merchant account to one institute and denies other tenants.
Active admin/staff sessions are required; staff branch restrictions are checked against
the database. Student portal self-service is not exposed by these staff billing routes.

`CASHFREE_NOTIFY_URL` is optional. Set a reachable HTTPS URL on the institute's
verified domain, or configure that URL directly in Cashfree's sandbox dashboard.
For local development, use a Cashfree-compatible HTTPS tunnel and configure the ERP's
tenant domain resolution for that host. Cashfree cannot call a localhost webhook.
Whitelist the checkout site's domain in the Cashfree dashboard.
If `CONTENT_SECURITY_POLICY` overrides the default, permit Cashfree's sandbox/SDK
frames as well as its HTTPS scripts and connections.
The SDK submits a hidden form to
`https://sandbox.cashfree.com/pg/view/sessions/checkout` even in modal mode. Successful
billing invoice responses for the configured institute add that exact destination
to `form-action`; other pages retain their configured policy. A self-only
`form-action` blocks this request and leaves the provider modal on its loading spinner.

## Database setup

Apply `migrations/20261029_cashfree_sandbox.sql` to the intended **test MySQL database**
before enabling checkout. It creates `cashfree_orders` only. This assumes the existing
multi-institute finance migration (`20260724_multi_institute_phase5_finance_assets.sql`)
and document-number sequences are already installed. Configure the institute's receipt prefix.
MySQL migrations do not run automatically at app startup. The SQLite initialization
path creates the order table through `init_sqlite_schema`; existing billing tenant
columns are prerequisites there too.

The Cashfree migration was applied to the local Docker `attn_billing_testing` database
for sandbox testing. No cloud database migration or deployment was performed.

## Local Docker testing

The web service publishes `127.0.0.1:8080:8080`. On this Windows Docker Desktop setup,
the previous dual-stack publishing accepted IPv6 localhost connections without
returning an HTTP response. Recreating only `web` with the IPv4 loopback mapping
restored both localhost and 127.0.0.1 requests; the MySQL/Redis containers and data were preserved.

Open `http://globalit.localhost:8080/login` and sign in with an institute-1 admin/staff
account for fee testing. The existing `localhost` and `127.0.0.1` hosts are configured
as the platform control plane; the institute portal uses `globalit.localhost`.

Checkout also supports the existing HTTP `globalit.127-0-0-1.nip.io` tenant host.
When the browser does not expose `crypto.randomUUID`, it generates a UUID v4 using
`crypto.getRandomValues` and preserves the same key across request retries. The
checkout script URL includes a revision so refreshed invoice pages load this fix.

A clearly labelled local test student (`CF-SANDBOX-LOCAL`) and INR 10 invoice were
created. The current test invoice is `/billing/invoice/491`. A real Cashfree sandbox
order was created successfully with the updated keys, and API verification returned
`ACTIVE`. No payment or receipt was posted. Complete the hosted modal checkout to
exercise successful payment and receipt posting.

The local-only smoke helper refuses to run outside the development Docker database:

```powershell
docker exec attn_billing_web python -m scripts.cashfree_docker_smoke migrate
docker exec attn_billing_web python -m scripts.cashfree_docker_smoke smoke
```

It reuses its labelled fixture and an existing active sandbox order, uses an ephemeral
signed staff session only against container loopback, and never prints session cookies,
API secrets, or payment session IDs. It verifies the actual HTTP invoice/order routes,
Cashfree API status, and rejection of unsigned webhooks. It does not complete a payment.

Use the official [sandbox test details](https://www.cashfree.com/docs/payments/online/resources/sandbox-environment)
in hosted checkout. Provider-originated webhook delivery still requires a reachable
HTTPS URL; the local-only HTTP endpoint cannot receive Cashfree callbacks directly.

## API

All staff calls require the normal Flask login cookie and `X-CSRFToken`. Requests
and responses are JSON. Create requests may include a UUID `Idempotency-Key` header;
reuse it after a timeout with exactly the same payment details.

`POST /billing/cashfree/orders`

```json
{
  "student_id": 123,
  "invoice_id": 456,
  "amount": "500.00",
  "phone": "9876543210",
  "email": "student@example.com",
  "name": "Student Name"
}
```

`invoice_id` may be omitted only when the student has exactly one payable invoice.
The server verifies invoice/student/institute ownership, branch access, INR amount,
current receipts/write-offs, and invoice status. It saves ownership before calling
`POST https://sandbox.cashfree.com/pg/orders` with API version `2023-08-01`.
The response contains `order_id` and `payment_session_id`.

`POST /billing/cashfree/orders/<order_id>/verify`

Fetches Cashfree's order and payments. Only an order marked `PAID` with a `SUCCESS`
payment, matching saved amount/currency/customer, can create a receipt. `ACTIVE`
orders return their existing session ID so checkout can resume without making a
second order. Browser redirects and SDK completion messages never authorize posting.

`POST /billing/cashfree/webhook`

Only this route is CSRF exempt. It authenticates the exact raw body using
`Base64(HMAC-SHA256(secret, timestamp + raw_body))` and constant-time comparison.
Successful-payment events trigger the same server-to-server verification and posting
path; failed/abandoned events are acknowledged without changing accounting.
Replay safety comes from the saved order, unique payment/receipt mappings, and
transactional posting, including for delayed legitimate webhook retries.

## Accounting and recovery

Receipt creation, invoice status, installment allocation, order completion, receipt
number allocation, and the activity log commit together. SQLite uses an immediate
write transaction; MySQL locks the invoice then the order. This serializes duplicate
confirmations and separate orders for the same invoice. No transaction stays locked
while waiting for Cashfree's API.
Verified sandbox Cashfree receipts cannot be changed through the manual receipt editor.

If an invoice is cancelled, written off, or its remaining balance is too small after
Cashfree receives payment, the order is marked `REVIEW` with its payment ID and an
audit entry. It does not create an overpayment receipt. Inspect these records with:

```sql
SELECT order_id, institute_id, invoice_id, amount_paise, cf_payment_id, updated_at
FROM cashfree_orders WHERE status = 'REVIEW';
```

An administrator must reconcile these through the merchant dashboard and the ERP's
accounting process. Automatic refunds and a reconciliation UI are outside this change.
Keep `cashfree_orders` when rolling back application code: it contains the durable
payment mapping and duplicate-posting protection. Sandbox code deliberately rejects
production Cashfree API URLs; a live-payment rollout needs separate configuration work.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest tests/test_cashfree_payments.py -q -p no:cacheprovider
node --test tests/cashfree_checkout.test.cjs
# Optional: starts and stops its own temporary mysqld process; requires mysqld on PATH.
$env:CASHFREE_RUN_MYSQL_TESTS='1'
.venv\Scripts\python.exe -m pytest tests/test_cashfree_mysql.py -q -p no:cacheprovider
```

Automated tests mock Cashfree and use disposable databases. They do not contact
Cashfree or the configured ERP database. The MySQL integration test applies the
actual migration to a temporary MySQL server and races duplicate deliveries and
distinct orders against the same invoice. That test passed locally on MySQL 9.4,
along with 46 payment backend tests and 14 frontend checks. The existing certificate
and bad-debt installment regression checks also passed.
Complete an interactive sandbox payment and signed webhook delivery with the full
credentials in your test environment before enabling checkout for users.

References: [2023-08-01 Create Order API](https://www.cashfree.com/docs/api-reference/payments/previous/v2023-08-01/orders/create),
[web checkout](https://www.cashfree.com/docs/payments/online/web/redirect),
[webhook signatures](https://www.cashfree.com/docs/payments/online/webhooks/signature-verification).
