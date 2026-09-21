import csv
import json
import os
import sqlite3
import time
from datetime import datetime, timezone

import requests

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
DB_PATH = "paper_trader.db"

STARTING_BANKROLL = float(os.getenv("STARTING_BANKROLL", "50"))
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.08"))
MAX_RISK_PCT = float(os.getenv("MAX_RISK_PCT", "0.06"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "5"))
MIN_LIQUIDITY = float(os.getenv("MIN_LIQUIDITY", "5000"))
MIN_HOURS_TO_RESOLUTION = float(os.getenv("MIN_HOURS_TO_RESOLUTION", "2"))


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            bankroll REAL NOT NULL,
            peak_bankroll REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            market_id TEXT NOT NULL,
            question TEXT NOT NULL,
            side TEXT NOT NULL,
            market_price REAL NOT NULL,
            estimated_probability REAL NOT NULL,
            edge REAL NOT NULL,
            position_size REAL NOT NULL,
            status TEXT NOT NULL,
            resolution_time TEXT,
            outcome REAL,
            pnl REAL
        )
    """)
    row = con.execute("SELECT bankroll, peak_bankroll FROM state WHERE id=1").fetchone()
    if row is None:
        con.execute(
            "INSERT INTO state (id, bankroll, peak_bankroll, updated_at) VALUES (1, ?, ?, ?)",
            (STARTING_BANKROLL, STARTING_BANKROLL, now_iso()),
        )
    con.commit()
    return con


def fetch_markets():
    params = {
        "active": "true",
        "closed": "false",
        "limit": 1000,
    }
    r = requests.get(GAMMA_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("data", [])


def as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def estimate_probability(market):
    """
    Phase 1 intentionally uses a neutral baseline.

    We are validating the data pipeline and paper-trading mechanics first.
    A future model can replace this function without changing the accounting
    or execution logic.
    """
    prices = market.get("outcomePrices")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except json.JSONDecodeError:
            prices = None

    if isinstance(prices, list) and prices:
        p = as_float(prices[0])
        if p is not None:
            return max(0.0, min(1.0, p))

    p = as_float(market.get("lastTradePrice"))
    return p if p is not None else None


def extract_price(market):
    prices = market.get("outcomePrices")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except json.JSONDecodeError:
            prices = None
    if isinstance(prices, list) and prices:
        p = as_float(prices[0])
        if p is not None:
            return p
    return as_float(market.get("lastTradePrice"))


def filter_candidates(markets):
    out = []
    for m in markets:
        if not m.get("active") or m.get("closed"):
            continue

        liquidity = as_float(m.get("liquidity")) or 0.0
        if liquidity < MIN_LIQUIDITY:
            continue

        price = extract_price(m)
        if price is None or price <= 0 or price >= 1:
            continue

        # Skip very short-dated markets when a parseable end date exists.
        end_date = m.get("endDate") or m.get("end_date")
        if end_date:
            try:
                end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                hours = (end - datetime.now(timezone.utc)).total_seconds() / 3600
                if hours < MIN_HOURS_TO_RESOLUTION:
                    continue
            except Exception:
                pass

        out.append(m)
    return out


def run():
    con = init_db()
    markets = fetch_markets()
    candidates = filter_candidates(markets)

    rows = []
    for m in candidates:
        price = extract_price(m)
        est = estimate_probability(m)
        if price is None or est is None:
            continue

        # Phase 1 neutral model => zero edge.
        # No paper trades are opened yet. This validates the pipeline safely.
        edge = est - price
        rows.append({
            "timestamp": now_iso(),
            "market_id": str(m.get("id", "")),
            "question": m.get("question", ""),
            "price": price,
            "estimated_probability": est,
            "edge": edge,
            "liquidity": as_float(m.get("liquidity")) or 0.0,
        })

    with open("latest_scan.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "timestamp", "market_id", "question", "price",
            "estimated_probability", "edge", "liquidity"
        ])
        w.writeheader()
        w.writerows(rows)

    summary = {
        "timestamp": now_iso(),
        "markets_fetched": len(markets),
        "candidates_after_filters": len(candidates),
        "starting_bankroll": STARTING_BANKROLL,
        "min_edge": MIN_EDGE,
        "max_risk_pct": MAX_RISK_PCT,
        "max_open_positions": MAX_OPEN_POSITIONS,
        "note": "Phase 1 pipeline only: no trades are opened until a validated probability model is added.",
    }
    with open("latest_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))
    con.close()


if __name__ == "__main__":
    run()
