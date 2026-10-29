# Student payment links (sandbox)

Invoice SMS messages keep the invoice download link and append a signed payment
link. Manual SMS reminders and automatic SMS reminders append it too. The invoice
detail screen shows the link for staff to copy or open. All integration testing
uses the local Docker database; no real student SMS messages were sent.

Students do not need an ERP login. The link opens a mobile-friendly payment page
and lets the payer choose:

- The next unpaid installment's remaining amount.
- The full outstanding invoice balance.

Payments settle installments in the ERP's existing installment order. For example,
an invoice for INR 1,000 with two INR 500 installments initially offers INR 500 or
INR 1,000. After INR 125 is received, the same link offers INR 375 or INR 875.
Once the invoice is settled, the page no longer offers checkout.

The URL contains signed invoice/institute/student identifiers, without an amount.
Amounts come from current receipts and write-offs whenever the page opens and are
checked again while the invoice is locked during order creation. An edited amount
or stale quote is rejected before opening checkout. Closed, cancelled, or written-off
invoices cannot accept payment.

## Configuration

```dotenv
CASHFREE_PAYMENT_LINKS_ENABLED=true
CASHFREE_PAYMENT_LINK_BASE_URL=http://globalit.127-0-0-1.nip.io:8080
CASHFREE_PAYMENT_LINK_DAYS=30
```

These values are enabled only in the ignored local `.env.docker` for sandbox tests.
The flag defaults to false elsewhere. Recreate `web` after changing its env file.
The base URL must belong to an active domain of the configured institute. If no
override is set, the institute's active primary domain is used with HTTPS; this
also supports the background reminder job without a Flask request context.

Apply `migrations/20261029_cashfree_student_payment_links.sql` after the original
Cashfree migration. SQLite initialization creates the corresponding table.
`cashfree_payment_link_orders` binds each public checkout to a digest of its exact
signed link and the selected payment option. No bearer token is stored there.
Private staff orders cannot be resumed or inspected using a public link.

This remains a sandbox integration. Real student collection needs the live gateway
implementation, a deployed public HTTPS tenant site, and provider webhook delivery.
A loopback test URL opens only on the machine running Docker.

## Access and accounting

Links expire after 30 days by default (configurable from 1 to 90 days). Tampered,
expired, wrong-purpose, and cross-tenant tokens are rejected. Browser-supplied
student/invoice IDs do not control the payable invoice. Public POST routes retain
CSRF protection and rate limits; only the existing signed webhook is CSRF exempt.

Public pages use `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and
no-index headers. Stored student phone/email details are not displayed; the payer
enters their contact information. Cashfree's exact checkout form destination is
permitted on the payment page through the existing scoped CSP handling.

Verified success uses the existing transaction-safe receipt, invoice status,
installment allocation, and audit flow. The original invoice author is retained
as the financial record's user attribution, while the link-order binding identifies
the student-link origin. Duplicate confirmations cannot create duplicate receipts.
The payment page displays a receipt confirmation only after checking the saved,
verified order and receipt against the link.

After checkout starts, its selected amount is fixed. If the ledger changes before
an ACTIVE checkout resumes, verification blocks that stale session and asks the
student to contact the institute. If payment has already reached Cashfree, existing
reconciliation rules apply; the integration never silently posts an overpayment.

## Local verification

```powershell
docker exec attn_billing_web python -m scripts.cashfree_docker_smoke migrate
docker exec attn_billing_web python -m scripts.cashfree_docker_smoke links-smoke
```

The helper prepares a labelled sandbox invoice with two installments, checks the
anonymous payment page, creates a real sandbox order, and previews both invoice
and automatic-reminder SMS integration with transport disabled or in dry-run mode.
It never sends an SMS or completes a payment.

Automated coverage includes dynamic balances, both student choices, stale/tampered
amounts, token expiry and tenant isolation, CSRF, public/private order isolation,
exactly-once posting, SMS composition, background-job operation without a request
context, and the actual MySQL migration and settlement flow.
