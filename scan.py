#!/usr/bin/env python
"""
scan.py — Batch engine for the watchlist leaderboard.

Fetches many tickers in a single yfinance call (benchmark once), runs each
through rs.compute(), and returns ranked rows. This same batch-fetch machinery
is reused by the RS Rating universe computation.
"""

import math

import rs
import universe


def _nz(x: float) -> float:
    """NaN -> 0.0, so a missing horizon doesn't poison the score."""
    return 0.0 if x is None or (isinstance(x, float) and math.isnan(x)) else x


def strength_score(excess: dict, slope_short: float) -> float:
    """Composite 'current strength' for ranking. Recent horizons weighted more."""
    return (0.4 * _nz(excess["3m"]) + 0.3 * _nz(excess["6m"])
            + 0.2 * _nz(excess["12m"]) + 0.1 * _nz(excess["1m"]))


def _build_rows(tickers, bench_close, closes, uni_scores, timeframe) -> list:
    """Build leaderboard row dicts for `tickers`. Failures carry an 'error' key."""
    rows = []
    for t in tickers:
        if t not in closes:
            rows.append({"ticker": t, "error": "no data"})
            continue
        try:
            res = rs.compute(closes[t], bench_close, timeframe)
            s = res["signals"]
            rows.append({
                "ticker": t,
                "verdict": s["verdict"],
                "vcolor": s["vcolor"],
                "excess": s["excess"],
                "slope": s["slope_short"],
                "score": strength_score(s["excess"], s["slope_short"]),
                "rating": universe.percentile(universe.raw_score(closes[t]), uni_scores),
            })
        except Exception as e:
            rows.append({"ticker": t, "error": str(e)})
    return rows


def scan_watchlist(tickers, benchmark: str, period: str, timeframe: str) -> list:
    """
    Run a whole watchlist. Returns row dicts sorted strongest-first (by score).
    """
    tickers = list(dict.fromkeys(t.upper() for t in tickers))
    bench_close = rs.fetch_close(benchmark, period)
    closes = rs.fetch_many(tickers, period)
    uni_scores = universe.ensure_scores(period)   # cached daily; builds on first run
    rows = _build_rows(tickers, bench_close, closes, uni_scores, timeframe)
    rows.sort(key=lambda r: r.get("score", float("-inf")), reverse=True)
    return rows


def scan_universe(benchmark: str, period: str, timeframe: str, top_n=50) -> list:
    """
    Rank the whole S&P 500 universe by RS Rating and return the top N as full
    leaderboard rows (sorted by rating, strongest first). top_n=None => all.

    Fast path: the universe scores are cached daily, so we only download price
    history for the N names we actually display.
    """
    uni_scores = universe.ensure_scores(period)
    ranked = sorted(uni_scores.items(), key=lambda kv: kv[1], reverse=True)
    top = [t for t, _ in (ranked[:top_n] if top_n else ranked)]
    bench_close = rs.fetch_close(benchmark, period)
    closes = rs.fetch_many(top, period)
    rows = _build_rows(top, bench_close, closes, uni_scores, timeframe)
    rows.sort(key=lambda r: r.get("rating", -1), reverse=True)
    return rows
