"""Client-mode CLI for the Retail Velocity Decision Tool.

Runs the shelf-risk decision on a client's own POS/velocity data: per-(retailer,
sku) scan velocity, an At-Risk / Warning / Safe classification against the
retailer's velocity floor, the scan revenue at risk, and — where a per-retailer
trade-spend rate is supplied — the trade-adjusted net at risk.

POS-shaped, so it uses the shared POS-intake layer (``lailara_engagement.pos``)
with the required ``week_convention`` / ``scan_basis`` declarations and reuses the
tested ``classify_shelf_status`` + per-retailer thresholds from the app (reuse,
not rebuild).

**Kroger trade-spend proxy (per DECISIONS.md 2026-08-05).** The item master
carries no Kroger trade-spend rate. When a client supplies per-retailer rates
(``rates.trade_spend_pct``) but omits Kroger, Kroger falls back to the
config-named proxy retailer's rate (``rates.trade_spend_proxy``, default "Regional
Group") — and that substitution is **disclosed** on the Kroger row and in a
methodology note. Never silent, never a platform schema change.

Usage:
    python client_mode.py --config engagement.yml --scans client-data/scans.csv \
        --stores client-data/stores.csv [--out client-output] [--final]
"""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent / "app"))
from calcs import classify_shelf_status          # noqa: E402  (app is import-rooted at app/)
from constants import RETAILER_THRESHOLDS          # noqa: E402

from lailara_engagement import (
    build_provenance,
    load_config,
    pos,
    read_table,
    validation_status_label,
    write_report,
)
from lailara_engagement import palette as P
from lailara_engagement.provenance import Provenance

TOOL = "retail-velocity-decision-tool"
TOOL_VERSION = "1.0"
DEFAULT_PROXY_TARGET = "Regional Group"


def resolve_trade_rate(retailer: str, rates_pct: dict, proxy_map: dict) -> tuple[float | None, str | None]:
    """Return (rate, proxied_from). A retailer with no own rate falls back to the
    config-named proxy retailer's rate; the proxy source is returned for
    disclosure. Never a silent substitution."""
    if retailer in rates_pct:
        return float(rates_pct[retailer]), None
    proxy_target = proxy_map.get(retailer, DEFAULT_PROXY_TARGET if retailer == "Kroger" else None)
    if proxy_target and proxy_target in rates_pct:
        return float(rates_pct[proxy_target]), proxy_target
    return None, None


def compute_shelf_risk(scans, stores, config):
    """Per-(retailer, sku) velocity + shelf status + revenue at risk, with the
    trade-adjusted net where a rate (or its proxy) exists."""
    rates = (config.raw.get("rates") or {})
    rates_pct = rates.get("trade_spend_pct") or {}
    proxy_map = rates.get("trade_spend_proxy") or {}
    thresholds = {**RETAILER_THRESHOLDS, **(config.basis.get("retailer_thresholds") or {})}

    df = scans.merge(stores[["store_id", "retailer"]], on="store_id", how="left")
    as_of = pd.Timestamp(config.as_of_date)
    df = df[df["week_ending"] <= as_of]
    weeks = sorted(df["week_ending"].dropna().unique())
    if not weeks:
        return {"retailers": [], "disclosures": []}, []
    mid = weeks[len(weeks) // 2]

    def velocity(block):
        # mean weekly units per carrying store for the (retailer, sku)
        g = block.groupby(["retailer", "sku"], as_index=False).agg(
            units=("units_sold", "sum"), stores=("store_id", "nunique"),
            wks=("week_ending", "nunique"))
        g["v"] = g["units"] / g["stores"].clip(lower=1) / g["wks"].clip(lower=1)
        return g[["retailer", "sku", "v"]]

    cur = velocity(df[df["week_ending"] > mid]).rename(columns={"v": "current_v"})
    tra = velocity(df[df["week_ending"] <= mid]).rename(columns={"v": "trailing_v"})
    vel = cur.merge(tra, on=["retailer", "sku"], how="outer").fillna({"current_v": 0.0, "trailing_v": 0.0})

    # revenue at risk needs per-(retailer, sku) scan dollars over the recent half.
    rev = (df[df["week_ending"] > mid].groupby(["retailer", "sku"], as_index=False)["dollars_sold"]
           .sum().rename(columns={"dollars_sold": "recent_dollars"}))
    vel = vel.merge(rev, on=["retailer", "sku"], how="left").fillna({"recent_dollars": 0.0})

    out_rows, disclosures = [], []
    for retailer, g in vel.groupby("retailer"):
        thr = float(thresholds.get(retailer, 1.5))
        classified = classify_shelf_status(g.assign(retailer=retailer), thr)
        at_risk = classified[classified["status"] == "At Risk"]
        rev_at_risk = round(float(at_risk["recent_dollars"].sum()), 2)
        rate, proxied_from = resolve_trade_rate(str(retailer), rates_pct, proxy_map)
        net_at_risk = round(rev_at_risk * (1 - rate), 2) if rate is not None else None
        note = None
        if proxied_from:
            note = f"trade-spend rate proxied from {proxied_from} ({rate:.1%})"
            disclosures.append(f"{retailer}: no own trade-spend rate — proxied from "
                               f"{proxied_from} ({rate:.1%}); item master carries no {retailer} rate.")
        out_rows.append({
            "retailer": str(retailer), "n_skus": int(len(g)), "n_at_risk": int(len(at_risk)),
            "velocity_floor": thr, "revenue_at_risk": rev_at_risk,
            "trade_rate": rate, "net_at_risk": net_at_risk, "proxy_note": note,
        })
    out_rows.sort(key=lambda r: r["revenue_at_risk"], reverse=True)
    summary = {"retailers": out_rows, "disclosures": disclosures,
               "total_at_risk_skus": sum(r["n_at_risk"] for r in out_rows),
               "total_revenue_at_risk": round(sum(r["revenue_at_risk"] for r in out_rows), 2)}
    return summary, out_rows


def _fmt_dollars(v):
    return "—" if v is None else f"${v:,.0f}"


def _deliverable_html(config, summary, rows, basis_word, window_label, limitations,
                      provenance: Provenance, *, draft: bool) -> str:
    esc = html.escape
    draft_class = " ll-draft" if draft else ""
    trows = "".join(
        f"<tr><td>{esc(r['retailer'])}{' *' if r['proxy_note'] else ''}</td>"
        f"<td class=num>{r['n_at_risk']}/{r['n_skus']}</td>"
        f"<td class=num>{r['velocity_floor']:.1f}</td>"
        f"<td class=num>{_fmt_dollars(r['revenue_at_risk'])}</td>"
        f"<td class=num>{('—' if r['trade_rate'] is None else f'{r['trade_rate']*100:.1f}%')}</td>"
        f"<td class=num>{_fmt_dollars(r['net_at_risk'])}</td></tr>"
        for r in rows
    )
    disc = "".join(f"<li>{esc(d)}</li>" for d in summary["disclosures"])
    disc_section = f"<section class=ll-section><h2 class=ll-h2>Proxy disclosures</h2><ul class=ll-limitations>{disc}</ul></section>" if disc else ""
    lim = "".join(f"<li>{esc(x)}</li>" for x in limitations)
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>Shelf-Risk & Velocity — {esc(config.client_name)}</title><style>{_css(draft)}</style></head>
<body class="{draft_class.strip()}"><main class=ll-page>
<header class=ll-header>
  <div class=ll-eyebrow>Lailara LLC · Retail Velocity</div>
  <h1 class=ll-title>Shelf-Risk &amp; Velocity</h1>
  <div class=ll-client>
    <div><span class=ll-k>Client</span> {esc(config.client_name)}</div>
    <div><span class=ll-k>Engagement</span> {esc(config.engagement_id)}</div>
    <div><span class=ll-k>As of</span> {esc(config.as_of_date.isoformat())}</div>
    <div><span class=ll-k>Prepared by</span> {esc(config.prepared_by)}</div>
  </div>
</header>
<section class=ll-banner>
  <div class=ll-score>{summary['total_at_risk_skus']} at-risk item-retailer positions</div>
  <div>{_fmt_dollars(summary['total_revenue_at_risk'])} {esc(basis_word)} revenue at risk</div>
  <div class=ll-basis>Basis: {esc(basis_word)} dollars on at-risk positions (velocity below the
       retailer floor) · Window: {esc(window_label)}. Net at risk = revenue × (1 − trade rate).
       Rows marked * use a disclosed proxy rate — see below.</div>
</section>
<section class=ll-section>
  <h2 class=ll-h2>By retailer</h2>
  <table class=ll-table><thead><tr><th>Retailer</th><th>At risk / SKUs</th><th>Velocity floor</th>
  <th>Revenue at risk</th><th>Trade rate</th><th>Net at risk</th></tr></thead><tbody>{trows}</tbody></table>
</section>
{disc_section}
<section class=ll-section>
  <h2 class=ll-h2>Data limitations</h2>
  <ul class=ll-limitations>{lim}</ul>
</section>
{provenance.to_html()}
</main></body></html>"""


def _css(draft: bool) -> str:
    draft_css = (
        ".ll-draft::before{content:'DRAFT';position:fixed;top:50%;left:50%;"
        "transform:translate(-50%,-50%) rotate(-32deg);font-family:var(--s);"
        "font-size:22vw;font-weight:700;color:rgba(204,16,10,.06);z-index:0;"
        "pointer-events:none;white-space:nowrap}" if draft else ""
    )
    return f"""
:root{{--s:{P.LL_SERIF};--f:{P.LL_SANS}}}
*{{box-sizing:border-box}}
body{{margin:0;background:{P.LL_CANVAS};color:{P.LL_TEXT};font-family:var(--f);line-height:1.6}}
.ll-page{{position:relative;z-index:1;max-width:{P.LL_MAX_WIDTH};margin:0 auto;padding:48px 24px}}
.ll-header{{border-bottom:1px solid {P.LL_GRIDLINE};padding-bottom:24px;margin-bottom:24px}}
.ll-eyebrow{{font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:{P.LL_RED};font-weight:600}}
.ll-title{{font-family:var(--s);font-weight:700;color:{P.LL_INK};font-size:34px;margin:8px 0 16px}}
.ll-client{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px 24px;font-size:14px}}
.ll-k{{display:block;color:{P.LL_TEXT_SEC};font-size:11px;text-transform:uppercase;letter-spacing:.04em}}
.ll-banner{{border-radius:2px;padding:16px 20px;margin-bottom:32px;background:{P.LL_SG_SURFACE};color:{P.LL_SG_DARK}}}
.ll-score{{font-family:var(--s);font-weight:700;font-size:22px}}
.ll-basis{{font-size:12px;color:{P.LL_TEXT_SEC};margin-top:8px}}
.ll-section{{margin:0 0 32px}}
.ll-h2{{font-family:var(--s);font-weight:700;color:{P.LL_INK};font-size:22px;
margin:0 0 12px;padding-bottom:6px;border-bottom:1px solid {P.LL_GRIDLINE}}}
.ll-table{{width:100%;border-collapse:collapse;font-size:14px}}
.ll-table th{{text-align:left;background:{P.LL_CHICAGO};color:#fff;padding:8px 12px}}
.ll-table td{{padding:8px 12px;border-bottom:1px solid {P.LL_GRIDLINE}}}
.ll-limitations{{margin:0;padding-left:20px}}.ll-limitations li{{margin-bottom:6px}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.ll-provenance{{margin-top:40px;background:{P.LL_CARD_BG};color:{P.LL_CARD_TEXT};
padding:20px 24px;border-radius:2px;font-size:13px}}
.ll-prov-title{{font-family:var(--s);font-weight:700;font-size:16px;margin-bottom:8px}}
.ll-provenance div{{margin-bottom:4px;color:{P.LL_CARD_SUBTITLE}}}
.ll-provenance strong{{color:{P.LL_CARD_TEXT}}}
.ll-prov-inputs{{width:100%;border-collapse:collapse;margin-top:8px}}
.ll-prov-inputs th{{text-align:left;border-bottom:1px solid rgba(255,255,255,.12);padding:4px 8px;color:{P.LL_CARD_MUTED}}}
.ll-prov-inputs td{{padding:4px 8px;border-bottom:1px solid rgba(255,255,255,.08);color:{P.LL_CARD_SUBTITLE}}}
.ll-prov-brand{{margin-top:12px;font-family:var(--s);color:{P.LL_CARD_MUTED}}}
{draft_css}
@media print{{body{{background:#fff}}}}
"""


def run(config_path: str, out_dir: str, args, *, final: bool = False) -> dict:
    config = load_config(config_path)
    ci = config.raw.get("inputs") or {}
    scans_path = args.scans or ci.get("scans")
    stores_path = args.stores or ci.get("stores")
    if not (scans_path and stores_path):
        raise SystemExit("missing required input(s): scans and/or stores.")
    week_conv, _wd = pos.resolve_week_convention(config)
    scan_basis = pos.resolve_scan_basis(config)
    basis_word = pos.scan_basis_label(scan_basis)

    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    scan_read = read_table(scans_path)
    store_read = read_table(stores_path)
    scan_report, scan_frame = pos.intake(
        scan_read, pos.scan_spec(tool=TOOL, version=TOOL_VERSION, week_convention=week_conv), config)
    from lailara_engagement import ColumnSpec, PreflightSpec, run_preflight
    store_spec = PreflightSpec(tool=TOOL, version=TOOL_VERSION, columns=[
        ColumnSpec(name="store_id", dtype="identifier", required=True, unique=True, spec_ref="INPUT-SPEC §Stores"),
        ColumnSpec(name="retailer", dtype="string", required=True, spec_ref="INPUT-SPEC §Stores")])
    store_report = run_preflight(store_read, store_spec, config)
    scan_report.disclosures.extend(pos.declared_disclosures(week_conv, scan_basis))

    reports = {"scans": scan_report, "stores": store_report}
    blocked = {k: r for k, r in reports.items() if not r.passed}
    provenance = build_provenance(
        tool=TOOL, tool_version=TOOL_VERSION, inputs=[scan_read, store_read], config=config,
        validation_status=validation_status_label("failed" if blocked else "clean",
                                                   sum(r.n_warnings for r in reports.values())),
        extra={"Week convention": week_conv, "Scan basis": f"{basis_word} dollars"})
    if blocked:
        written = {}
        for key, report in blocked.items():
            p = write_report(report, config, str(out), provenance=provenance, draft=not final,
                             basename=f"data-readiness-{key}", title=f"Velocity Data Readiness — {key}")
            written[key] = p["html"]
        return {"status": "blocked", "blocked_files": list(blocked), "readiness_reports": written}

    stores = pos.to_frame(store_read, store_report, store_spec)
    summary, rows = compute_shelf_risk(scan_frame, stores, config)
    first, last = scan_frame["week_ending"].min(), scan_frame["week_ending"].max()
    window_label = f"scan weeks {first.strftime('%b %d, %Y')} – {last.strftime('%b %d, %Y')}"

    limitations = [f"[{k}] {f.message}" for k, r in reports.items() for f in r.findings if f.severity == "warning"]
    if not limitations:
        limitations.append("No warnings — inputs passed preflight cleanly.")

    import csv as _csv
    csv_path = out / "shelf-risk-by-retailer.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["retailer"])
        w.writeheader(); w.writerows(rows)
    html_path = out / "shelf-risk-velocity.html"
    html_path.write_text(_deliverable_html(config, summary, rows, basis_word, window_label,
                                            limitations, provenance, draft=not final), encoding="utf-8")
    return {"status": "ok", "total_at_risk_skus": summary["total_at_risk_skus"],
            "total_revenue_at_risk": summary["total_revenue_at_risk"],
            "n_proxy_disclosures": len(summary["disclosures"]),
            "report": str(html_path), "csv": str(csv_path),
            "n_warnings": sum(r.n_warnings for r in reports.values())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="retail-velocity client mode")
    ap.add_argument("--config", required=True)
    ap.add_argument("--scans"); ap.add_argument("--stores")
    ap.add_argument("--out", default="client-output"); ap.add_argument("--final", action="store_true")
    args = ap.parse_args(argv)
    result = run(args.config, args.out, args, final=args.final)
    if result["status"] == "blocked":
        print("BLOCKED — data not ready. Readiness report(s):")
        for key, path in result["readiness_reports"].items():
            print(f"  {key}: {path}")
        return 3
    print(f"{result['total_at_risk_skus']} at-risk positions · "
          f"{_fmt_dollars(result['total_revenue_at_risk'])} revenue at risk "
          f"({result['n_proxy_disclosures']} proxy disclosure(s))")
    print(f"report -> {result['report']}\ncsv    -> {result['csv']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
