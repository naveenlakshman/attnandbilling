# Phase 0 — Baseline and isolation test harness

This directory is deliberately non-production. It records the current schema ownership decisions, route scopes, overlapping two-institute fixtures, and read-only Global IT reconciliation metrics.

Run against local Docker/MySQL:

```powershell
docker cp phase0 attn_billing_web:/tmp/phase0
docker cp scratch/test_multi_institute_phase0.py attn_billing_web:/tmp/test_multi_institute_phase0.py
docker compose exec -T -e PYTHONPATH=/app web python /tmp/test_multi_institute_phase0.py
docker compose exec -T -e PYTHONPATH=/app web python /tmp/phase0/global_it_reconciliation.py
```

The isolation test reports `KNOWN_GAP_DETECTED` for current single-institute behavior. That is a successful Phase 0 characterization, not proof that tenant isolation has been implemented. Future phases must replace each known-gap assertion with an enforced-isolation assertion.

The reconciliation script performs read-only aggregate queries and emits no student names, phone numbers, emails, document paths, or credentials.

After Phase 1, the current ownership registry contains 73 tables. The frozen
`global_it_baseline_20260722.json` intentionally remains the pre-Phase-1
65-table baseline for later reconciliation.
