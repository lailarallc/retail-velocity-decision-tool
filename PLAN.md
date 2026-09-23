# Plan — Cinderhaven Velocity Decision Tool

## Current Goal (2026-05-16)

Harden the live demo and close universal gaps vs. competitors, then build
the highest-leverage feature (competitive benchmarking).

**Audience:** Cold-landing CEO of a $20-25M food company checking the link
from their phone or laptop after receiving a pitch email. Zero onboarding
tolerance. Needs to see portfolio health in <30 seconds.

**Strategic position:** Only open-source prescriptive decision tool in the
retail/CPG analytics space. Broadest decision coverage at any price point.
Main vulnerabilities: no mobile support, no category benchmarking, cold-load
latency on first daily visit.

---

## Completed Work

### Portfolio Health Dashboard (2026-05-15) ✓

- [x] A1: Remove Story mode
- [x] A2: Portfolio health data layer (`get_portfolio_summary()`)
- [x] A3: Portfolio health landing page (KPIs, risk cards, status bar)
- [x] A4: Drill-down navigation (risk cards → decision modes)
- [x] B1: Narrative "so what" insights on all 8 decision modes
- [x] B2: Time-series trend charts (Shelf Defense, Production, Launch)
- [x] C: End-to-end polish

### Infrastructure (2026-05-13–15) ✓

- [x] Connection management refactor (context manager)
- [x] Health check endpoint + fly.toml check config
- [x] CI pipeline (ruff lint + pytest, 26 tests)
- [x] Retailer pitch export (Excel + PDF)
- [x] README updated, LICENSE restored
- [x] Persistent cache volume, single-worker config

---

## Next Moves (from Audit Phase 4)

### Move 5: Production Hardening v2 — DONE ✓

- [x] Pin all dependency versions with ceilings in `app/requirements.txt`
- [x] Move `_get_sku_meta()` from `decisions/expansion.py` to `data.py` with
      `@cache.memoize` — fixes architecture bypass + adds caching
- [x] Replace `dangerously_allow_html` in all files with Dash `html.Span`/
      `html.B` components (8 callers + 5 direct usages across 7 files)
- [x] Add Sentry SDK integration (opt-in via SENTRY_DSN env var)
- [x] Fix pre-existing bug: undefined `n_total` in rationalization.py

### Move 6: Cold-Load Performance — DONE ✓

- [x] Add `get_portfolio_summary()` to `warm_default_view()` in `data.py`
      so the landing page is pre-cached before the app serves traffic
- [x] Verify first-visitor load time is <3 seconds with warm cache — HTML 0.4s, full render ~3s

### Move 7: Mobile Responsiveness — DONE ✓

- [x] Add `@media (max-width: 767.98px)` breakpoints to `assets/style.css`
- [x] Stack `.dash-body` vertically on narrow screens (chart below grid)
- [x] Collapse sidebar into toggle button on mobile widths
      (dbc.Collapse + clientside callback)
- [x] AG Grid height auto on narrow screens via CSS override
- [x] Bootstrap responsive columns: `xs=12, md=3` / `xs=12, md=9`
- [x] Metric cards + risk cards wrap into 2×2 grid on mobile
- [x] Verify on iPhone SE / Pixel viewport sizes — CSS breakpoint at 767.98px covers both (375px, 393px)

### Move 8: Competitive Benchmarking — DONE ✓

Large effort, very high impact. Transforms the tool from "here's your data"
to "here's your data in context" — the #1 thing every paid tool charges for.

- [x] Design category field in `dim_products` (product_line → market category)
- [x] Generate synthetic category-level velocity averages (by retailer × week)
      `stg_category_benchmarks` table: 2,492 rows across 3 categories × 8 retailers
- [x] New data function: `get_category_benchmark(retailer, product_line)`
      Plus `get_category_benchmark_weekly(retailer, category, weeks)` for trends
- [x] Add benchmark reference lines to Shelf Defense chart ("category avg")
      Blue dotted vline on bar chart, hline on trend chart, metric card, insight text
- [x] Add benchmark comparison to Production Planning (metric card)
- [x] Add benchmark KPI card to Portfolio Health landing page
- [ ] Consider standalone "How do I compare?" decision mode (deferred — Move 10)

Done when: At-risk SKUs in Shelf Defense show whether they're below the
category average too (not just below the retailer threshold). A prospect
sees how Cinderhaven performs relative to its competitive set. ✓ DONE

### Move 9: Test Coverage Expansion — DONE ✓

Medium effort. Strengthens "production-quality code" signal for technical
evaluators.

- [x] Data function shape tests (mock DB, assert column names + types)
- [x] Callback dispatch tests (verify mode routing logic)
- [x] Pitch export edge case tests (empty DataFrames)
- [x] Edge case tests (empty retailer, NaN values, zero-row data)
- [x] Chart helper tests (layout structure, hbar padding, annotations)
- [x] Category benchmark graceful degradation tests

Done when: Test count is 50+ with coverage on the surfaces where bugs
historically appeared (data functions, callbacks, edge cases). ✓ 80 tests

---

### Move 10: Data Integrity & Calculation Correctness — DONE ✓

`/improve` pass focused on reconciliation with Postgres and calculation/assumption correctness.
3-agent deep audit (data integrity, calculation correctness, assumption audit).

- [x] Fix forecast rounding (premature .round(2) on cases)
- [x] Promo baseline guard — return excluded count, show in UI
- [x] Pricing elasticity guard — use min_discount threshold
- [x] Seasonal factor — read clip bounds from THRESHOLDS dict
- [x] Production trend status — detect zero/NaN prior → Accelerating
- [x] Promo exclusion transparency in UI
- [x] Pricing "Insufficient data" verdict for NaN elasticity
- [x] Shelf defense current_v null detection before fillna
- [x] Regional benchmark fallback with logging
- [x] Rationalization wholesale_price null guard
- [x] Launch classifier dead branch cleanup
- [x] Scan data grain validation check (new)
- [x] Cost completeness validation check (new)
- [x] Portfolio health label clarity
- [x] Missing threshold constants added to THRESHOLDS dict
- [x] Expansion "All equivalent" tier
- [x] Unused import cleanup

Done when: All 17 findings fixed, 163 tests passing, no new lint issues. ✓

### Move 11: Mart Layer Migration — DONE ✓

Migrate all SQL reads from staging tables to dbt mart equivalents. Prevent
reload_postgres.py from overwriting canonical platform tables.

- [x] Disable reload_postgres.py with hard guard
- [x] Add margin_per_unit, margin_pct to dim_products mart (dbt model + schema)
- [x] Repoint stg_stores → dim_stores (chain_name → retailer)
- [x] Repoint stg_scan_data → fct_scan_data
- [x] Repoint stg_promotions → fct_promotions (retailer_id → retailer)
- [x] Remove stg_sku_costs JOINs — read costs from dim_products
- [x] Delete Python margin re-derivation — read mart margin_per_unit
- [x] Update validation.py, seed_benchmarks.py, test files
- [x] Reorder search_path: public_marts first
- [x] Verify: 929 SQL comparisons, zero drifts at 1e-10

Done when: No stg_* reads for shared data, margin from mart, verified parity. ✓

---

## Improvement Arc (2026-07-31) — CEO/CFO readiness

**Goal:** Make the tool trustworthy to a cold-landing CEO/CFO who must grasp
the purpose in <30s. Triggered by `/improve` + `/ce` code review + `/ui review`.
Constraint: no Postgres SSOT changes — code/CSS only.

**Why now:** Three combined reviews (4-agent ce code review, ui-review tool,
30s comprehension read). Theme: the tool leads with dollar figures and several
are wrong — the real risk to CEO trust, not layout.

### Phase 1 — Confirmed bugs — DONE ✓
- [x] C1: Expansion mode crashes (NameError on tied/single-store scores)
- [x] C2: Headline "$X/week at risk" overstated — sums cross-retailer revenue
- [x] Pitch export mislabels store-week margin as "Margin/Unit"
- [x] 28-vs-29 headline/subhead reads as a bug
- [x] Launch Health wall-of-zeros → empty state

### Phase 2 — Agent-found — DONE ✓
- [x] Promo duration_weeks off-by-one (~25% understated) + single-week $0
- [x] Pricing "Stop promoting" false-fail when post_v is NaN (no data yet)
- [x] Rationalization headline cut-count ≠ Cut-candidates tab count (renamed to "discontinuation candidates")
- [x] Duplicate at-risk classification unified into data._shelf_risk_breakdown
- [x] Seasonal YoY window overlaps day 364 (double-counted week)
- [x] Pruning shelf_cost labeled "margin" but uses wholesale price (relabeled revenue + clamp)

### Phase 3 — Lower stakes / polish — DONE ✓
- [x] Contrast fail on .ph-bar-segment (dropped redundant in-bar number)
- [x] Dash dropdowns off-brand (CSS override block)
- [x] "cs" → "cases"
- [x] Demo label ("Demo · synthetic sample data" in sidebar + footer)
- [x] 56% at-risk: investigated — data-real (cross-retailer union), thresholds NOT tuned, documented in DECISIONS 2026-07-31
- [x] Test gaps: classify_quadrant now imported not copied; expansion tie, single-week promo, NaN post_v covered

**Definition of done:** Met — every fix has a regression test; 183 tests green;
dollar figures corrected; no NameError; AA contrast passes (once deployed).

### Out of scope (not done — need separate decision)
- Postgres SSOT / schema / reseeds (user constraint)
- fct_scan_data indexing (SSOT change; noted in DECISIONS 2026-07-18)
- Launch Health N+1 seq-scan perf fix (0 launches today; will bite when launches exist) — data.py get_launch_velocity_curve
- get_pricing_data correlated-EXISTS on filtered path (perf; extends the known zero-index issue)
- **DEPLOY: all 16 commits are local; the live site still shows old behavior until pushed to main (CI auto-deploys)**

---

## Improvement History

### 2026-09-23 — Audit (health check only)
- **Findings:** 0 critical, 5 important, 3 nice-to-have
- **Top concerns:** HANDOFF/PLAN stale since 2026-07-31 (21 commits incl. client mode unrecorded; audit was due 2026-08-30). Pitch export Production sheet turns missing case-pack into "0 cases" and rounds cases to whole numbers (HANDOFF next-step #1 still open). Stale app/Dockerfile + app/fly.toml conflict with the real deploy config; test_health.py never exercises the real /health route.
- **Action taken:** Audit only — no fixes this session
- **Next review:** 2026-10-21

### 2026-07-31 — Improvement pass (`/improve` + `/ce` review + `/ui review`)
- **Trigger:** User-initiated combined review. Goal: CEO/CFO-ready, purpose clear in <30s. Constraint: no Postgres SSOT changes.
- **What was reviewed:** 4-agent ce code review (correctness/calc, maintainability/Python, performance, testing), ui-review-skill against live site, 30-second comprehension read of the rendered landing page.
- **What was fixed (16 commits, 172→183 tests):**
  - 5 confirmed bugs: Expansion NameError crash; overstated headline $ (cross-retailer leak); pitch-export margin mislabel; 28-vs-29 wording; Launch Health empty state.
  - 6 agent-found: promo ~25% $ understatement + single-week $0; pricing "Stop promoting" false-fail; rationalization naming collision; seasonal 364-day double-count; pruning revenue/margin mislabel; unified duplicate at-risk classification.
  - Polish: AA contrast; on-brand dropdowns; "cases"; demo-dataset label; classify_quadrant tested against shipped code.
- **56% at-risk:** Investigated (read-only) — data-real cross-retailer union, per-retailer rates healthy (~17% avg). Kept the number, thresholds untouched, documented in DECISIONS.md per user decision.
- **Deferred:** Launch Health N+1 perf (0 launches now); get_pricing_data correlated-EXISTS; fct_scan_data index (SSOT).
- **NOT DEPLOYED:** all commits local; push to main to reach production.
- **Next review:** 2026-08-30

### 2026-05-22 — Improvement pass
- **Trigger:** User-initiated `/improve` focused on data reconciliation and calculation correctness
- **What was reviewed:** Calculation chains (production, promo ROI, pricing, expansion), data contract validation, assumption hardcoding, UI transparency
- **What was fixed:** 17 findings — 5 critical, 8 important, 4 nice-to-have (see Move 10)
- **Deferred:** None — all findings addressed
- **Next review:** 2026-06-22

---

## Out of Scope

- ML-based forecasting (seasonal factor is honest for synthetic data)
- Alerting/notifications (pull-only is fine for portfolio demo)
- Real data connectivity (productization decision, not portfolio decision)
- New decision modes (9 is comprehensive enough)
- Cache warming redesign (current pattern works)
