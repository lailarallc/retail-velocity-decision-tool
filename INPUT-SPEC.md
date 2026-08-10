# Retail Velocity Decision Tool — Client Data Input Specification

Runs the shelf-risk decision on your POS/velocity data: per-(retailer, sku) scan
velocity, an At-Risk / Warning / Safe classification against the retailer's
velocity floor, the scan revenue at risk, and — where a per-retailer trade-spend
rate is supplied — the trade-adjusted net at risk. POS-shaped, so it uses the
shared POS-intake contract (`lailara_engagement.pos`).

## §Scans — weekly POS scan movement (required)
`store_id`, `sku`, `week_ending`, `units_sold`, `dollars_sold` — the canonical POS
scan columns (see the shared contract). `week_ending` is validated on the
declared weekday.

## §Stores — the store dimension (required)
| Column | Type | Required |
|---|---|---|
| `store_id` | identifier (text) | **required, unique** |
| `retailer` | string | **required** — the retailer each store belongs to |

## Required declarations (`basis:`)
- **`week_convention`** — validates every `week_ending` weekday.
- **`scan_basis`** — `retail_scan` | `wholesale`; carried into provenance and
  printed next to the revenue-at-risk figure.

## Per-retailer trade-spend rates + the Kroger proxy (`rates:`)
Optional. When supplied, the deliverable shows trade-adjusted **net at risk**
(revenue × (1 − rate)).

```yaml
rates:
  trade_spend_proxy: {Kroger: "Regional Group"}   # Kroger has no own rate
  trade_spend_pct:
    Walmart: 0.11
    Regional Group: 0.09
    # ... one per retailer that has a rate
```

The item master carries no Kroger trade-spend rate. A retailer with no own rate
falls back to the config-named **proxy** retailer's rate, and that substitution is
**disclosed** on the retailer's row and in a methodology note — never a silent
substitution, and never a platform schema change (see DECISIONS.md 2026-08-05).

## Column mapping (`engagement.yml`)
Map your headers under `columns:`; run:
`python client_mode.py --config engagement.yml --scans client-data/scans.csv --stores client-data/stores.csv`
