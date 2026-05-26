"""Local web UI for browsing scraped listings, tracking status, and adding notes.

Run with: python -m apartment_hunter.web
Then open http://localhost:5000
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from flask import Flask, abort, render_template, request

from . import db

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_ROOT / "data" / "listings.db"


def create_app(db_path: Path | str = DEFAULT_DB) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = str(db_path)

    def get_conn():
        return db.connect(app.config["DB_PATH"])

    @app.template_filter("amenities")
    def parse_amenities(s):
        if not s:
            return []
        try:
            return json.loads(s)
        except Exception:
            return []

    @app.template_filter("money")
    def fmt_money(v):
        if v is None:
            return "—"
        return f"${v:,}"

    @app.template_filter("num")
    def fmt_num(v, places=0):
        if v is None:
            return "—"
        if places == 0 and float(v).is_integer():
            return str(int(v))
        return f"{v:.{places}f}"

    @app.route("/")
    def index():
        conn = get_conn()
        status_filter = request.args.getlist("status")
        source_filter = request.args.getlist("source")
        sort = request.args.get("sort", "score_desc")
        show_hidden = request.args.get("hidden") == "1"
        search = request.args.get("q", "").strip() or None
        try:
            min_score = float(request.args.get("min_score", "0") or 0)
        except ValueError:
            min_score = 0
        try:
            max_price = int(request.args["max_price"]) if request.args.get("max_price") else None
        except ValueError:
            max_price = None
        try:
            min_beds = float(request.args["min_beds"]) if request.args.get("min_beds") else None
        except ValueError:
            min_beds = None

        rows = db.query_listings(
            conn,
            statuses=status_filter or None,
            sources=source_filter or None,
            min_score=min_score,
            max_price=max_price,
            min_beds=min_beds,
            show_hidden=show_hidden,
            search=search,
            sort=sort,
        )
        return render_template(
            "index.html",
            rows=rows,
            statuses=db.STATUSES,
            status_counts=db.status_counts(conn),
            source_counts=db.source_counts(conn),
            status_filter=status_filter,
            source_filter=source_filter,
            sort=sort,
            show_hidden=show_hidden,
            search=search or "",
            min_score=min_score,
            max_price=max_price or "",
            min_beds=min_beds if min_beds is not None else "",
        )

    @app.route("/listing/<source>/<external_id>")
    def detail(source, external_id):
        conn = get_conn()
        row = db.get_one(conn, source, external_id)
        if not row:
            abort(404)
        return render_template("listing.html", row=row, statuses=db.STATUSES)

    @app.route("/listing/<source>/<external_id>/status", methods=["POST"])
    def update_status(source, external_id):
        conn = get_conn()
        status = request.form.get("status", "new")
        try:
            db.set_status(conn, source, external_id, status)
        except ValueError:
            abort(400)
        row = db.get_one(conn, source, external_id)
        return render_template("_status_pill.html", row=row, statuses=db.STATUSES)

    @app.route("/listing/<source>/<external_id>/notes", methods=["POST"])
    def update_notes(source, external_id):
        conn = get_conn()
        db.set_notes(conn, source, external_id, request.form.get("notes", ""))
        return '<span class="text-xs text-emerald-600">saved</span>'

    @app.route("/listing/<source>/<external_id>/hide", methods=["POST"])
    def toggle_hide(source, external_id):
        conn = get_conn()
        row = db.get_one(conn, source, external_id)
        if not row:
            abort(404)
        db.set_hidden(conn, source, external_id, not bool(row["hidden"]))
        return "", 204

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    app = create_app(args.db)
    print(f"\n  Apartment Hunter UI -> http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
