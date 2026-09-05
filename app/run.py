"""Cinderhaven Velocity Tool -- Dash application entry point."""

from __future__ import annotations

import os
import pathlib
import threading

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env")

import sentry_sdk  # noqa: E402

if os.environ.get("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        traces_sample_rate=0.1,
    )

import dash_bootstrap_components as dbc  # noqa: E402
from dash import Dash, Input, Output, State  # noqa: E402
from flask import jsonify  # noqa: E402

from callbacks import register_callbacks
from data import init_cache, warm_cache, warm_default_view
from decisions.shelf_defense import register_callbacks as shelf_cbs
from decisions.production import register_callbacks as prod_cbs
from decisions.promo_roi import register_callbacks as promo_cbs
from decisions.expansion import register_callbacks as expansion_cbs
from decisions.pruning import register_callbacks as pruning_cbs
from decisions.rationalization import register_callbacks as rationalization_cbs
from decisions.launch_health import register_callbacks as launch_cbs
from decisions.pricing_power import register_callbacks as pricing_cbs
from layout import create_layout
from lailara_frame import wrap

app = Dash(
    __name__,
    title="Retail Velocity Decision Tool | Lailara LLC",
    update_title=None,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    meta_tags=[
        {"name": "description", "content": "Eight decisions, from shelf defense to pricing power, worked on a 1.2M-row dataset."},
        {"property": "og:title", "content": "Retail Velocity Decision Tool"},
        {"property": "og:description", "content": "Eight decisions, from shelf defense to pricing power, worked on a 1.2M-row dataset."},
        {"property": "og:type", "content": "website"},
        {"property": "og:url", "content": "https://velocity.lailarallc.com/"},
        {"property": "og:image", "content": "https://lailarallc.com/og/s/velocity.png"},
        {"property": "og:image:secure_url", "content": "https://lailarallc.com/og/s/velocity.png"},
        {"property": "og:image:type", "content": "image/png"},
        {"property": "og:image:width", "content": "1200"},
        {"property": "og:image:height", "content": "630"},
        {"property": "og:image:alt", "content": "Retail Velocity Decision Tool"},
        {"name": "twitter:card", "content": "summary_large_image"},
        {"name": "twitter:image", "content": "https://lailarallc.com/og/s/velocity.png"},
    ],
)
server = app.server
init_cache(server)


@server.route("/health")
def health():
    try:
        from db import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
        return jsonify({"status": "ok"})
    except Exception:
        return jsonify({"status": "db_unavailable"}), 503


app.layout = wrap(
    create_layout(),
    tool_name="Velocity Tool",
    no_container=True,
    footer_note=(
        "Demo — Cinderhaven Provisions is a fictional brand on a synthetic "
        "dataset, built to demonstrate the tool. Three years of weekly scan "
        "data through 2025-12-27, 6 retail channels."
    ),
)
register_callbacks(app)
shelf_cbs(app)
prod_cbs(app)
promo_cbs(app)
expansion_cbs(app)
pruning_cbs(app)
rationalization_cbs(app)
launch_cbs(app)
pricing_cbs(app)

from validation import log_validation_results, validate_data_contract

try:
    log_validation_results(validate_data_contract())
except Exception:
    import logging
    logging.getLogger("validation").warning(
        "Data contract validation skipped — database unavailable at startup",
        exc_info=True,
    )

app.clientside_callback(
    """function(n, is_open) {
        var next = !is_open;
        var label = next ? '☰ Hide Filters' : '☰ Show Filters & Navigation';
        return [next, label];
    }""",
    [Output("sidebar-collapse", "is_open"), Output("sidebar-toggle", "children")],
    Input("sidebar-toggle", "n_clicks"),
    State("sidebar-collapse", "is_open"),
    prevent_initial_call=True,
)

warm_default_view()
threading.Thread(target=warm_cache, daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True, port=8050)
