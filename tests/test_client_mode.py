"""Client-mode tests for the Retail Velocity Decision Tool (checklist §6).

Skipped unless the shared ``lailara_engagement`` lib is installed. Fixtures
generated on the fly — no client identifiers, no committed data. The headline
case is the Kroger disclosed proxy (DECISIONS.md 2026-08-05).
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("lailara_engagement")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import client_mode  # noqa: E402

AS_OF = pd.Timestamp("2025-12-27")                 # Saturday
WEEKS = [AS_OF - timedelta(weeks=(7 - i)) for i in range(8)]   # 8 Saturdays, mid split at wk 4


def _world():
    """Walmart store W1 (SKU-A low velocity -> at risk) + Kroger store K1 (SKU-A low
    -> at risk). Kroger has NO trade rate in config -> proxy to Regional Group."""
    stores = pd.DataFrame([("W1", "Walmart"), ("K1", "Kroger")], columns=["store_id", "retailer"])
    rows = []
    for sid in ("W1", "K1"):
        for w in WEEKS:
            rows.append((sid, "CHP-AS-001", w.strftime("%Y-%m-%d"), 2, 20.0))  # velocity 2.0 < 2.5 floor
    scans = pd.DataFrame(rows, columns=["store_id", "sku", "week_ending", "units_sold", "dollars_sold"])
    return stores, scans


def _write(d: Path):
    stores, scans = _world()
    sp, stp = d / "scans.csv", d / "stores.csv"
    scans.to_csv(sp, index=False)
    stores.to_csv(stp, index=False)
    return sp, stp


def _cfg(d: Path, *, rates=True, columns=None):
    import yaml
    cfg = {"client": {"name": "Cinderhaven Provisions (demo)"}, "engagement": {"id": "T-1"},
           "as_of_date": "2025-12-27", "demo": True,
           "basis": {"week_convention": "week_ending_saturday", "scan_basis": "retail_scan"},
           "columns": columns or {}}
    if rates:
        cfg["rates"] = {"trade_spend_proxy": {"Kroger": "Regional Group"},
                        "trade_spend_pct": {"Walmart": 0.11, "Regional Group": 0.09}}
    p = d / "engagement.demo.yml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return p


def _args(scans=None, stores=None):
    from types import SimpleNamespace
    return SimpleNamespace(scans=scans, stores=stores)


def test_clean_run_classifies_at_risk(tmp_path):
    sp, stp = _write(tmp_path)
    res = client_mode.run(str(_cfg(tmp_path)), str(tmp_path / "out"), _args(str(sp), str(stp)))
    assert res["status"] == "ok"
    assert res["total_at_risk_skus"] == 2          # SKU-A at both Walmart and Kroger
    assert Path(res["report"]).is_file()


def test_kroger_uses_disclosed_proxy_rate(tmp_path):
    sp, stp = _write(tmp_path)
    res = client_mode.run(str(_cfg(tmp_path)), str(tmp_path / "out"), _args(str(sp), str(stp)))
    assert res["n_proxy_disclosures"] == 1          # Kroger proxied
    html = Path(res["report"]).read_text(encoding="utf-8")
    assert "Proxy disclosures" in html
    assert "proxied from Regional Group" in html
    # Walmart has its own rate — not proxied.
    import csv as _csv
    rows = {r["retailer"]: r for r in _csv.DictReader(open(res["csv"], encoding="utf-8"))}
    assert rows["Walmart"]["proxy_note"] in ("", "None")
    assert "Regional Group" in rows["Kroger"]["proxy_note"]
    # Kroger net at risk uses the 9% proxy rate: revenue*(1-0.09).
    kr_rev = float(rows["Kroger"]["revenue_at_risk"])
    assert round(float(rows["Kroger"]["net_at_risk"]), 2) == round(kr_rev * 0.91, 2)


def test_no_rates_means_no_net_but_still_runs(tmp_path):
    sp, stp = _write(tmp_path)
    res = client_mode.run(str(_cfg(tmp_path, rates=False)), str(tmp_path / "out"), _args(str(sp), str(stp)))
    assert res["status"] == "ok"
    assert res["n_proxy_disclosures"] == 0


def test_window_label_tracks_scan_span_not_a_hardcode(tmp_path):
    """The rendered Window label must be the ACTUAL scan-week span and move with
    the data. The suite asserted at-risk counts and proxy notes, never the
    window text — a hardcoded span matching the demo would pass, the failure
    mode behind trade-spend quoting 26 weeks of data as 'trailing 52 weeks'.

    Both halves: assert each distinct span's full window substring is present,
    AND assert the other span's substring (a stand-in for a hardcode) is absent."""
    sp, stp = _write(tmp_path)
    cfg = _cfg(tmp_path)
    scans = pd.read_csv(sp)
    wk = pd.to_datetime(scans["week_ending"])
    first_a, last = wk.min(), wk.max()
    early_b = first_a - timedelta(weeks=20)          # still a Saturday, on-grid

    def win(first):
        return f"scan weeks {first.strftime('%b %d, %Y')} – {last.strftime('%b %d, %Y')}"

    res_a = client_mode.run(str(cfg), str(tmp_path / "out_a"), _args(str(sp), str(stp)))
    html_a = Path(res_a["report"]).read_text(encoding="utf-8")
    assert win(first_a) in html_a and win(early_b) not in html_a

    # Span B: one earlier scan week for store W1 -> window start moves back.
    r0 = scans.iloc[0].to_dict()
    r0["week_ending"] = early_b.strftime("%Y-%m-%d")
    pd.concat([scans, pd.DataFrame([r0])], ignore_index=True).to_csv(sp, index=False)
    res_b = client_mode.run(str(cfg), str(tmp_path / "out_b"), _args(str(sp), str(stp)))
    html_b = Path(res_b["report"]).read_text(encoding="utf-8")
    assert win(early_b) in html_b and win(first_a) not in html_b

    for html in (html_a, html_b):
        low = html.lower()
        assert "trailing 52" not in low and "52-week" not in low and "52 weeks" not in low
        assert "365d" not in low


def test_missing_units_blocks(tmp_path):
    sp, stp = _write(tmp_path)
    pd.read_csv(sp).drop(columns=["units_sold"]).to_csv(sp, index=False)
    res = client_mode.run(str(_cfg(tmp_path)), str(tmp_path / "out"), _args(str(sp), str(stp)))
    assert res["status"] == "blocked" and "scans" in res["blocked_files"]


def test_off_convention_week_blocks(tmp_path):
    sp, stp = _write(tmp_path)
    df = pd.read_csv(sp)
    df.loc[0, "week_ending"] = "2025-12-29"  # Monday
    df.to_csv(sp, index=False)
    res = client_mode.run(str(_cfg(tmp_path)), str(tmp_path / "out"), _args(str(sp), str(stp)))
    assert res["status"] == "blocked"
