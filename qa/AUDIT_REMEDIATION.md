# Audit remediation — 23 September 2026

Baseline: main `0f7e54f`. Scope: make the procurement workflow reliable against the independently reproduced audit failures, support the supplied partner formats, and document measurable limitations. A jury score is not guaranteed by this checklist.

The baseline passed 76 QA and 25 backend tests, TypeScript checking and the production build. Additional adversarial scenarios nevertheless found the following failures. Existing tests passing is not acceptance of these scenarios.

## Release-blocking regression scenarios

| Area | Reproduction | Required outcome |
|---|---|---|
| Persistence | Save stock 17 with an empty sales history; restart | Restore 17 and the empty history, never overwrite it with demo data |
| Concurrent edits | Submit SALE 1 while stock is edited from 10 to 20 | Serializable result 19 or 20; never silently restore stale stock 9 |
| Record identity | Edit B, delete preceding A, save B | B changes; C remains intact |
| Excel round trip | Purchase 50, export inventory workbook, import unchanged workbook | Preserve 50 units in transit |
| Regular B2B demand | Twelve weekly purchases of 100 by the same customer | Do not exclude all regular purchases as one-off outliers |
| Trailing stockout | Last 16 days have no transactions because stock is unavailable | Keep the calendar through the data cutoff and recover lost demand |
| Inbound timing | Stock 10, demand 10/day, inbound 1 tomorrow and 100 on day 10 | Expose the shortage between deliveries |
| Explainability | Same SKU, warehouses with different last sale dates | Chart and recommendation use one cutoff and identical forecast values |

## Other required corrections

- Normalize partial weekly trend buckets and make forecasts invariant to merely extending their display horizon.
- Validate nonnegative monetary fields, support fractional package sizes and normalize physical stock minus reservations.
- Do not invent an ETA silently; explicitly handle unknown and overdue inbound.
- Make product deletion truthful, protect every spreadsheet export from formula interpretation, and reject idempotency key reuse with a different payload.
- Preserve unsaved inventory documents across navigation; active subtab clicks must not clear them.
- Ignore stale table responses, correct chart period semantics and use local calendar dates.
- Complete RU/EN/KK UI messages and respect numeric format preferences.
- Remove horizontal scrolling from inventory tabs and tables at 320px and above. Baseline at 390px: tabs 343/494px, table 342/560px client/scroll widths.

## Partner data and evidence

The supplied Systeme Electric and IEK archives contain 12 Excel workbooks. They contain 77,312 and 171,603 dated sales-history records respectively. The baseline parser does not recognize their original schemas. A rejected original workbook returns HTTP 422 without overwriting the existing data; this is a missing adapter, separate from the inventory round-trip data loss.

The bundled EKT sample is synthetic (18,861 sales, 27 SKUs, two warehouses). Documentation must not call it real partner data. Synthetic data is permitted by the case. Do not fabricate customer identifiers, prices, exact daily stockout intervals, or lead times and present them as observed facts.

Acceptance also requires an import reconciliation report, temporal backtest against a simple baseline, a reproducible end-to-end demonstration, and explicit limitations. Optional LLM integration or supplier email dispatch is not a substitute for the five required procurement capabilities.

## Collaboration and delivery

Work is isolated in `fix/audit-hardening`. Small commits separate validation/import, calculation, persistence/API and frontend fixes. Changes are checked before publishing. The other team's unmerged branch is not overwritten. This file records the baseline and acceptance contract; completed verification is recorded separately when implementation is ready.
