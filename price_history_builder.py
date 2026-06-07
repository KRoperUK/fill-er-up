#!/usr/bin/env python3
"""
Builds a compact national price-history series from the fuel-price snapshots.

Each `fuel_prices.json` release is a full snapshot (~1.7 MB); this distils one
point per day — the national average per fuel — into a tiny `price_history.json`
that the app can fetch and chart.

Usage:
    python price_history_builder.py update --feed .data/fuel_prices.json --date 2026-06-06-1119
    python price_history_builder.py backfill [--limit N]
"""

import argparse
import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

FUELS = ["E10", "E5", "B7", "SDV"]
REPO = "KRoperUK/fill-er-up"
DOCS_PATH = "docs/price_history.json"
DATA_PATH = ".data/price_history.json"


def national_averages(feed: dict) -> Dict[str, float]:
    """Mean price per fuel across every station in a snapshot, in pence (1 dp)."""
    totals = {f: 0.0 for f in FUELS}
    counts = {f: 0 for f in FUELS}
    for result in feed.get("results", []):
        if result.get("status") != "success":
            continue
        data = result.get("data") or {}
        for station in data.get("stations", []) or []:
            prices = (station or {}).get("prices") or {}
            for fuel in FUELS:
                value = _to_price(prices.get(fuel))
                if value is not None:
                    totals[fuel] += value
                    counts[fuel] += 1
    return {f: round(totals[f] / counts[f], 1) for f in FUELS if counts[f] > 0}


def _to_price(raw) -> Optional[float]:
    """Tolerant parse: numbers or numeric strings; ignore null / non-positive."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _day(tag_or_date: str) -> str:
    """`data-2026-06-06-1119` or `2026-06-06-1119` -> `2026-06-06`."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", tag_or_date)
    return m.group(1) if m else tag_or_date


def _load_history(path: str) -> List[dict]:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f).get("points", [])
    return []


def _save_history(points: List[dict]) -> None:
    points = sorted(points, key=lambda p: p["date"])
    payload = {
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "points": points,
    }
    for path in (DOCS_PATH, DATA_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)
    print(f"Wrote {len(points)} points to {DOCS_PATH} and {DATA_PATH}")


def _upsert(points: List[dict], date: str, averages: Dict[str, float]) -> List[dict]:
    if not averages:
        return points
    point = {"date": date, **averages}
    points = [p for p in points if p["date"] != date]
    points.append(point)
    return points


def update(feed_path: str, date: str) -> None:
    with open(feed_path) as f:
        feed = json.load(f)
    points = _upsert(_load_history(DOCS_PATH), _day(date), national_averages(feed))
    _save_history(points)


def backfill(limit: Optional[int]) -> None:
    session = requests.Session()
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        session.headers["Authorization"] = f"Bearer {token}"

    releases = []
    page = 1
    while True:
        resp = session.get(
            f"https://api.github.com/repos/{REPO}/releases",
            params={"per_page": 100, "page": page},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        releases.extend(batch)
        page += 1

    data_releases = [r for r in releases if r["tag_name"].startswith("data-")]
    data_releases.sort(key=lambda r: r["tag_name"], reverse=True)
    if limit:
        data_releases = data_releases[:limit]

    points: List[dict] = []
    seen = set()
    for rel in data_releases:
        day = _day(rel["tag_name"])
        if day in seen:
            continue  # one point per day; newest tag wins (sorted desc)
        asset = next((a for a in rel.get("assets", []) if a["name"] == "fuel_prices.json"), None)
        if not asset:
            continue
        try:
            feed = session.get(asset["browser_download_url"], timeout=60).json()
        except Exception as e:  # noqa: BLE001 — skip a bad snapshot, keep going
            print(f"  skip {rel['tag_name']}: {e}")
            continue
        averages = national_averages(feed)
        if averages:
            points.append({"date": day, **averages})
            seen.add(day)
            print(f"  {day}: {averages}")
    _save_history(points)


STATIONS_DATA_PATH = ".data/station_history.json"


def station_prices(feed: dict) -> Dict[str, Dict[str, float]]:
    """Per-station prices keyed by site id (matching the app's Station.id)."""
    out: Dict[str, Dict[str, float]] = {}
    for result in feed.get("results", []):
        if result.get("status") != "success":
            continue
        for station in (result.get("data") or {}).get("stations", []) or []:
            sid = (station or {}).get("site_id")
            if not sid:
                continue  # Costco etc. have no site_id; skip (app falls back locally)
            prices = station.get("prices") or {}
            entry = {f: v for f in FUELS if (v := _to_price(prices.get(f))) is not None}
            if entry:
                out[str(sid)] = entry
    return out


def _data_releases(session: requests.Session, days: int) -> List[dict]:
    """The most recent `days` data-* releases, one per day (newest tag wins)."""
    releases, page = [], 1
    while True:
        resp = session.get(
            f"https://api.github.com/repos/{REPO}/releases",
            params={"per_page": 100, "page": page}, timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        releases.extend(batch)
        page += 1
    data = sorted(
        (r for r in releases if r["tag_name"].startswith("data-")),
        key=lambda r: r["tag_name"], reverse=True,
    )
    chosen, seen = [], set()
    for rel in data:
        day = _day(rel["tag_name"])
        if day not in seen:
            seen.add(day)
            chosen.append(rel)
        if len(chosen) >= days:
            break
    return chosen


def build_stations(days: int) -> None:
    """Rebuild a rolling per-station history (last `days`) from recent releases.

    Aligned format keeps it compact:
        {"dates": [...], "stations": {"<id>": {"E10": [.., null, ..], ...}}}
    """
    session = requests.Session()
    if token := os.environ.get("GITHUB_TOKEN"):
        session.headers["Authorization"] = f"Bearer {token}"

    # acc[id][fuel][date] = price
    acc: Dict[str, Dict[str, Dict[str, float]]] = {}
    dates: List[str] = []
    for rel in _data_releases(session, days):
        day = _day(rel["tag_name"])
        asset = next((a for a in rel.get("assets", []) if a["name"] == "fuel_prices.json"), None)
        if not asset:
            continue
        try:
            feed = session.get(asset["browser_download_url"], timeout=60).json()
        except Exception as e:  # noqa: BLE001
            print(f"  skip {rel['tag_name']}: {e}")
            continue
        dates.append(day)
        for sid, prices in station_prices(feed).items():
            for fuel, value in prices.items():
                acc.setdefault(sid, {}).setdefault(fuel, {})[day] = value
        print(f"  {day}: {sum(len(p) for p in station_prices(feed).values())} prices")

    dates = sorted(set(dates))
    stations_out: Dict[str, dict] = {}
    for sid, fuels in acc.items():
        entry = {}
        for fuel, by_date in fuels.items():
            if len(by_date) >= 2:  # need at least 2 points to chart
                entry[fuel] = [by_date.get(d) for d in dates]
        if entry:
            stations_out[sid] = entry

    payload = {
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dates": dates,
        "stations": stations_out,
    }
    os.makedirs(os.path.dirname(STATIONS_DATA_PATH), exist_ok=True)
    with open(STATIONS_DATA_PATH, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"Wrote {len(stations_out)} stations x {len(dates)} days to {STATIONS_DATA_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_update = sub.add_parser("update", help="add today's averages from a local snapshot")
    p_update.add_argument("--feed", default=".data/fuel_prices.json")
    p_update.add_argument("--date", required=True, help="release tag or date")

    p_backfill = sub.add_parser("backfill", help="rebuild national history from releases")
    p_backfill.add_argument("--limit", type=int, default=None)

    p_stations = sub.add_parser("stations", help="rebuild rolling per-station history")
    p_stations.add_argument("--days", type=int, default=30)

    args = parser.parse_args()
    if args.command == "update":
        update(args.feed, args.date)
    elif args.command == "backfill":
        backfill(args.limit)
    elif args.command == "stations":
        build_stations(args.days)


if __name__ == "__main__":
    main()
