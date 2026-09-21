# Polymarket Paper Trader

Paper-only research bot. It never places real orders or connects to a wallet.

## What it does
- Pulls public Polymarket market data.
- Filters active markets.
- Scores candidate markets using a configurable heuristic.
- Records hypothetical trades against a $50 virtual bankroll.
- Stores all scans/trades locally in GitHub Actions artifacts.
- Runs on a schedule via GitHub Actions.

## Important
This is an experiment, not a claim of profitability. The first version deliberately does **not** use real-money execution.

## Configuration
Environment variables:
- STARTING_BANKROLL (default 50)
- MIN_EDGE (default 0.08)
- MAX_RISK_PCT (default 0.06)
- MAX_OPEN_POSITIONS (default 5)
- MIN_LIQUIDITY (default 5000)
- MIN_HOURS_TO_RESOLUTION (default 2)
