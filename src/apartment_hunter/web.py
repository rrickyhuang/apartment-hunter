"""Local web UI for browsing scraped listings, tracking status, and adding notes.

Run with: python -m apartment_hunter.web
Then open http://localhost:5000
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

import yaml
from flask import Flask, abort, make_response, redirect, render_template, request, url_for

from . import db
from .scoring import Criteria, passes_hard_filters, score

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_ROOT / "data" / "listings.db"
CRITERIA_PATH = PROJECT_ROOT / "config" / "criteria.yaml"

# Fields the form posts. Keep in sync with config.html.
KNOWN_SOURCES = ["rentals_ca", "rentfaster", "kijiji", "craigslist"]
WEIGHT_KEYS = ["price", "location", "size", "amenities"]


def _load_criteria_yaml() -> dict:
    with open(CRITERIA_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_criteria_yaml(data: dict) -> None:
    with open(CRITERIA_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def _csv_list(s: str) -> list[str]:
    """Split a 'a, b, c\\nd' string into a clean list."""
    if not s:
        return []
    parts = []
    for chunk in s.replace("\n", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


class _RowAsListing:
    """Minimal adapter so scoring.score() can read a sqlite Row without pydantic."""
    __slots__ = ("price", "beds", "sqft", "title", "description", "address",
                 "city", "amenities")

    def __init__(self, row, amenities_list):
        self.price = row["price"]
        self.beds = row["beds"]
        self.sqft = row["sqft"]
        self.title = row["title"]
        self.description = row["description"]
        self.address = row["address"]
        self.city = row["city"]
        self.amenities = amenities_list


# --- Scrape-on-demand state ---------------------------------------------------
# A single background scrape may run at a time. The UI polls /scrape/status to
# render the button's current state.
_scrape_state = {
    "running": False,
    "started_at": None,     # epoch seconds when scrape began
    "finished_at": None,    # epoch seconds when last scrape ended
    "new_count": None,      # how many new listings the last scrape inserted
    "error": None,          # last error message if any
    "source_results": {},   # {source: {fetched, new, dropped?, error?}}
    "refresh_pending": False,  # consumed once by /scrape/status to trigger HX-Refresh
}
_scrape_lock = threading.Lock()

# --- Auto-scrape scheduler state ---------------------------------------------
# A single daemon thread polls the schedule config and kicks off scrapes when
# the configured interval has elapsed. State here is in-memory only; the
# enabled flag and interval persist in criteria.yaml.
_scheduler_state = {
    "last_run_at": None,   # epoch seconds of last auto-triggered run
    "next_run_at": None,   # epoch seconds when next auto run is due
}
_scheduler_started = False
_scheduler_lock = threading.Lock()


def _run_scrape_thread(db_path: str) -> None:
    """Runs the full scraper pipeline. Updates _scrape_state for the UI.

    Calls scrapers directly (not via run.main) so it can use db.connect()
    (no DDL) and report per-source results without going through sys.exit().
    """
    # Import locally to keep scraper deps out of the web startup path.
    from .run import build_scrapers

    source_results: dict[str, dict] = {}
    failed_sources: list[str] = []
    before: int | None = None
    after: int | None = None

    try:
        criteria = Criteria.load(CRITERIA_PATH)
    except Exception as e:
        log.exception("scrape: failed to load criteria")
        with _scrape_lock:
            _scrape_state["running"] = False
            _scrape_state["finished_at"] = time.time()
            _scrape_state["error"] = f"criteria load failed: {e}"
            _scrape_state["refresh_pending"] = True
        return

    conn = db.connect(db_path)
    try:
        before = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    except Exception:
        pass

    for scraper in build_scrapers(criteria):
        src = scraper.source
        try:
            items = scraper.fetch()
        except Exception as e:
            log.exception("scrape: %s fetch failed", src)
            source_results[src] = {"error": str(e)}
            failed_sources.append(src)
            continue

        new_count = 0
        drop_count = 0
        for listing in items:
            try:
                is_new = db.upsert(conn, listing)
                if is_new:
                    new_count += 1
                ok, _ = passes_hard_filters(listing, criteria)
                if ok:
                    sc = score(listing, criteria)
                else:
                    sc = {"total": 0.0, "price": 0.0, "location": 0.0, "size": 0.0, "amenities": 0.0}
                sub = {k: sc[k] for k in ("price", "location", "size", "amenities")}
                db.set_score(conn, listing.source, listing.external_id, sc["total"], sub=sub)
            except (sqlite3.Error, KeyError, ValueError, TypeError) as e:
                log.warning("upsert/score failed for %s: %s", listing.url, e)
                drop_count += 1
        source_results[src] = {"fetched": len(items), "new": new_count}
        if drop_count:
            source_results[src]["dropped"] = drop_count
        log.info("source=%s fetched=%d new=%d dropped=%d", src, len(items), new_count, drop_count)

    try:
        after = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    except Exception:
        pass

    error_msg: str | None = None
    if failed_sources:
        all_failed = len(failed_sources) == len(source_results)
        verb = "All scrapers failed" if all_failed else "Scrapers failed"
        error_msg = f"{verb}: {', '.join(failed_sources)}"

    with _scrape_lock:
        _scrape_state["running"] = False
        _scrape_state["finished_at"] = time.time()
        _scrape_state["refresh_pending"] = True
        _scrape_state["source_results"] = source_results
        _scrape_state["error"] = error_msg
        if before is not None and after is not None:
            _scrape_state["new_count"] = max(0, after - before)


def _scrape_view_state() -> dict:
    """Snapshot of _scrape_state for templates (incl. derived fields)."""
    with _scrape_lock:
        s = dict(_scrape_state)
    now = time.time()
    s["elapsed"] = int(now - s["started_at"]) if s["started_at"] else None
    s["just_finished"] = (
        not s["running"]
        and s["finished_at"] is not None
        and (now - s["finished_at"]) < 4
    )
    return s


def _trigger_scrape(db_path: str) -> bool:
    """Start a scrape thread if none is running. Returns True if started."""
    with _scrape_lock:
        if _scrape_state["running"]:
            return False
        _scrape_state["running"] = True
        _scrape_state["started_at"] = time.time()
        _scrape_state["error"] = None
        _scrape_state["refresh_pending"] = False
    threading.Thread(
        target=_run_scrape_thread, args=(db_path,), daemon=True
    ).start()
    return True


def _scheduler_loop(db_path: str) -> None:
    """Background loop: re-reads schedule from criteria.yaml every tick so
    enabling/disabling or changing interval takes effect without a restart."""
    while True:
        try:
            cfg = _load_criteria_yaml()
            sched = cfg.get("schedule", {}) or {}
            enabled = bool(sched.get("enabled"))
            interval_min = max(1, int(sched.get("interval_minutes") or 60))
        except Exception as e:
            log.warning("scheduler: failed to read criteria: %s", e)
            enabled, interval_min = False, 60

        now = time.time()
        if enabled:
            last = _scheduler_state["last_run_at"]
            due = last is None or (now - last) >= interval_min * 60
            with _scheduler_lock:
                _scheduler_state["next_run_at"] = (
                    (last or now) + interval_min * 60 if last else now
                )
            if due:
                if _trigger_scrape(db_path):
                    with _scheduler_lock:
                        _scheduler_state["last_run_at"] = now
                        _scheduler_state["next_run_at"] = now + interval_min * 60
                    log.info("scheduler: triggered auto-scrape")
        else:
            with _scheduler_lock:
                _scheduler_state["next_run_at"] = None
        time.sleep(30)


def _rescore_all(conn, criteria: Criteria) -> int:
    """Re-score every listing in the DB against `criteria`. Returns count."""
    rows = db.all_listings(conn)
    for r in rows:
        try:
            amens = json.loads(r["amenities"]) if r["amenities"] else []
        except Exception:
            amens = []
        adapter = _RowAsListing(r, amens)
        ok, _ = passes_hard_filters(adapter, criteria)
        if ok:
            sc = score(adapter, criteria)
        else:
            sc = {"total": 0.0, "price": 0.0, "location": 0.0, "size": 0.0, "amenities": 0.0}
        sub = {k: sc[k] for k in ("price", "location", "size", "amenities")}
        db.set_score(conn, r["source"], r["external_id"], sc["total"], sub=sub, commit=False)
    conn.commit()
    return len(rows)


def create_app(db_path: Path | str = DEFAULT_DB) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = str(db_path)

    db.init_db(db_path)  # create tables / run migrations once at startup

    global _scheduler_started
    if not _scheduler_started:
        _scheduler_started = True
        threading.Thread(
            target=_scheduler_loop, args=(str(db_path),), daemon=True
        ).start()

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

    def _parse_filters():
        """Pull the standard listing filters off request.args. Shared by
        the list view and the map's GeoJSON endpoint so both honor the
        same query string."""
        status_filter = request.args.getlist("status")
        source_filter = request.args.getlist("source")
        sort = request.args.get("sort", "score_desc")
        show_hidden = request.args.get("hidden") == "1"
        starred_only = request.args.get("starred") == "1"
        show_nonviable = request.args.get("nonviable") == "1"
        search = request.args.get("q", "").strip() or None

        criteria_min_rent = None
        if not show_nonviable:
            try:
                cfg = _load_criteria_yaml()
                criteria_min_rent = int(cfg.get("hard_filters", {}).get("min_rent") or 0) or None
            except Exception as e:
                log.warning("could not read criteria for min_rent filter: %s", e)
        try:
            min_score = float(request.args.get("min_score", "0") or 0)
        except ValueError:
            min_score = 0
        try:
            max_score = float(request.args["max_score"]) if request.args.get("max_score") else None
        except ValueError:
            max_score = None
        try:
            max_price = int(request.args["max_price"]) if request.args.get("max_price") else None
        except ValueError:
            max_price = None
        try:
            min_beds = float(request.args["min_beds"]) if request.args.get("min_beds") else None
        except ValueError:
            min_beds = None
        return {
            "status_filter": status_filter,
            "source_filter": source_filter,
            "sort": sort,
            "show_hidden": show_hidden,
            "starred_only": starred_only,
            "show_nonviable": show_nonviable,
            "search": search,
            "criteria_min_rent": criteria_min_rent,
            "min_score": min_score,
            "max_score": max_score,
            "max_price": max_price,
            "min_beds": min_beds,
        }

    @app.route("/")
    def index():
        conn = get_conn()
        status_filter = request.args.getlist("status")
        source_filter = request.args.getlist("source")
        sort = request.args.get("sort", "score_desc")
        show_hidden = request.args.get("hidden") == "1"
        starred_only = request.args.get("starred") == "1"
        # "Hide non-viable" is on by default — listings priced below the
        # current min_rent get filtered out. Pass &nonviable=1 to see them.
        show_nonviable = request.args.get("nonviable") == "1"
        search = request.args.get("q", "").strip() or None

        # Pull min_rent from criteria so the filter tracks the user's config.
        criteria_min_rent = None
        if not show_nonviable:
            try:
                cfg = _load_criteria_yaml()
                criteria_min_rent = int(cfg.get("hard_filters", {}).get("min_rent") or 0) or None
            except Exception as e:
                log.warning("could not read criteria for min_rent filter: %s", e)
        try:
            min_score = float(request.args.get("min_score", "0") or 0)
        except ValueError:
            min_score = 0
        try:
            max_score = float(request.args["max_score"]) if request.args.get("max_score") else None
        except ValueError:
            max_score = None
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
            max_score=max_score,
            min_price=criteria_min_rent,
            max_price=max_price,
            min_beds=min_beds,
            show_hidden=show_hidden,
            starred_only=starred_only,
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
            show_nonviable=show_nonviable,
            criteria_min_rent=criteria_min_rent,
            starred_only=starred_only,
            search=search or "",
            min_score=min_score,
            max_score=max_score or "",
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

    @app.route("/listing/<source>/<external_id>/star", methods=["POST"])
    def toggle_star(source, external_id):
        conn = get_conn()
        row = db.get_one(conn, source, external_id)
        if not row:
            abort(404)
        db.set_starred(conn, source, external_id, not bool(row["starred"]))
        row = db.get_one(conn, source, external_id)
        return render_template("_star_button.html", row=row)

    @app.route("/listing/<source>/<external_id>/quick_status", methods=["POST"])
    def quick_status(source, external_id):
        """Used by inline card dropdown. Returns just the visible status pill."""
        conn = get_conn()
        status = request.form.get("status", "new")
        try:
            db.set_status(conn, source, external_id, status)
        except ValueError:
            abort(400)
        row = db.get_one(conn, source, external_id)
        return render_template("_card_status.html", row=row, statuses=db.STATUSES)

    @app.context_processor
    def inject_scrape_state():
        return {"scrape_state": _scrape_view_state()}

    @app.route("/scrape", methods=["POST"])
    def scrape_start():
        """Kick off a background scrape if one isn't already running."""
        _trigger_scrape(app.config["DB_PATH"])
        return render_template("_scrape_button.html", scrape_state=_scrape_view_state())

    @app.route("/scrape/status", methods=["GET"])
    def scrape_status():
        state = _scrape_view_state()
        # Consume the refresh_pending flag — fires HX-Refresh exactly once,
        # which then reloads the page with fresh listings.
        should_refresh = False
        with _scrape_lock:
            if _scrape_state["refresh_pending"]:
                _scrape_state["refresh_pending"] = False
                should_refresh = True
        resp = make_response(render_template("_scrape_button.html", scrape_state=state))
        if should_refresh:
            resp.headers["HX-Refresh"] = "true"
        return resp

    @app.route("/config", methods=["GET"])
    def config_view():
        cfg = _load_criteria_yaml()
        with _scheduler_lock:
            sched_state = dict(_scheduler_state)
        return render_template(
            "config.html",
            cfg=cfg,
            known_sources=KNOWN_SOURCES,
            saved=request.args.get("saved") == "1",
            rescored=request.args.get("rescored"),
            error=None,
            scheduler_state=sched_state,
        )

    @app.route("/config", methods=["POST"])
    def config_save():
        f = request.form
        try:
            new_cfg = {
                "hard_filters": {
                    "max_rent": int(f.get("max_rent") or 0),
                    "min_rent": int(f.get("min_rent") or 0),
                    "min_beds": float(f.get("min_beds") or 0),
                    "cities": _csv_list(f.get("cities", "")),
                    "deal_breakers": _csv_list(f.get("deal_breakers", "")),
                    "sources": {
                        src: f.get(f"src_{src}") == "on" for src in KNOWN_SOURCES
                    },
                },
                "weights": {k: float(f.get(f"w_{k}") or 0) for k in WEIGHT_KEYS},
                "preferences": {
                    "target_rent": int(f.get("target_rent") or 0),
                    "preferred_neighborhoods": _csv_list(f.get("preferred_neighborhoods", "")),
                    "min_sqft": int(f.get("min_sqft") or 0),
                    "target_sqft": int(f.get("target_sqft") or 0),
                    "nice_to_have": _csv_list(f.get("nice_to_have", "")),
                },
                "alert_threshold": float(f.get("alert_threshold") or 0),
                "schedule": {
                    "enabled": f.get("schedule_enabled") == "on",
                    "interval_minutes": max(1, int(f.get("schedule_interval_minutes") or 60)),
                },
            }
        except ValueError as e:
            return render_template(
                "config.html", cfg=_load_criteria_yaml(),
                known_sources=KNOWN_SOURCES, error=f"Bad number: {e}", saved=False, rescored=None,
            )

        total_w = sum(new_cfg["weights"].values())
        if abs(total_w - 1.0) > 0.001:
            return render_template(
                "config.html", cfg=new_cfg, known_sources=KNOWN_SOURCES,
                error=f"Weights must sum to 1.0 (got {total_w:.3f}). Adjust the four weight fields.",
                saved=False, rescored=None,
            )
        if new_cfg["hard_filters"]["min_rent"] > new_cfg["hard_filters"]["max_rent"]:
            return render_template(
                "config.html", cfg=new_cfg, known_sources=KNOWN_SOURCES,
                error="min_rent cannot exceed max_rent.", saved=False, rescored=None,
            )

        _save_criteria_yaml(new_cfg)
        # Re-score everything in the DB against the new criteria.
        criteria = Criteria.load(CRITERIA_PATH)
        n = _rescore_all(get_conn(), criteria)
        return redirect(url_for("config_view", saved=1, rescored=n))

    @app.route("/listing/<source>/<external_id>/hide", methods=["POST"])
    def toggle_hide(source, external_id):
        conn = get_conn()
        row = db.get_one(conn, source, external_id)
        if not row:
            abort(404)
        db.set_hidden(conn, source, external_id, not bool(row["hidden"]))
        return "", 204

    @app.route("/map")
    def map_view():
        # Page itself carries no listing data — markers are fetched via
        # /api/listings.geojson so we can stream the same query-string
        # filters the list view uses.
        conn = get_conn()
        f = _parse_filters()
        return render_template(
            "map.html",
            qs=request.query_string.decode(),
            statuses=db.STATUSES,
            status_counts=db.status_counts(conn),
            source_counts=db.source_counts(conn),
            status_filter=f["status_filter"],
            source_filter=f["source_filter"],
            sort=f["sort"],
            show_hidden=f["show_hidden"],
            show_nonviable=f["show_nonviable"],
            criteria_min_rent=f["criteria_min_rent"],
            starred_only=f["starred_only"],
            search=f["search"] or "",
            min_score=f["min_score"],
            max_score=f["max_score"] or "",
            max_price=f["max_price"] or "",
            min_beds=f["min_beds"] if f["min_beds"] is not None else "",
        )

    @app.route("/api/listings.geojson")
    def listings_geojson():
        conn = get_conn()
        f = _parse_filters()
        rows = db.query_listings(
            conn,
            statuses=f["status_filter"] or None,
            sources=f["source_filter"] or None,
            min_score=f["min_score"],
            max_score=f["max_score"],
            min_price=f["criteria_min_rent"],
            max_price=f["max_price"],
            min_beds=f["min_beds"],
            show_hidden=f["show_hidden"],
            starred_only=f["starred_only"],
            search=f["search"],
            sort=f["sort"],
            limit=2000,
            with_coords=True,
        )
        features = []
        for r in rows:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["lng"], r["lat"]]},
                "properties": {
                    "source": r["source"],
                    "external_id": r["external_id"],
                    "title": r["title"],
                    "price": r["price"],
                    "beds": r["beds"],
                    "score": r["score"],
                    "url": r["url"],
                    "detail_url": url_for("detail", source=r["source"], external_id=r["external_id"]),
                    "status": r["status"],
                    "starred": bool(r["starred"]),
                },
            })
        return {"type": "FeatureCollection", "features": features}

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
