#!/usr/bin/env python
"""
universe.py — IBD-style RS Rating (1-99).

The RS Rating ranks a stock's *own* 12-month price performance against a broad
universe and expresses it as a percentile from 1 (worst) to 99 (best). 99 means
it has outperformed 99% of the universe.

Method (classic IBD weighting): a weighted blend of trailing returns with the
most recent quarter weighted double, then percentile-ranked across the universe.

The universe is a built-in ~130-name large-cap basket (no web scraping, so the
packaged .exe stays self-contained). Per-day scores are cached on disk, so only
the first scan of each day pays the batch-download cost.
"""

import csv
import io
import json
import urllib.request
from datetime import date
from pathlib import Path

import rs

# Current S&P 500 constituents, fetched once and cached on disk. The app needs
# internet for quotes anyway, so this isn't a real loss of self-containment; if
# the fetch ever fails we fall back to the built-in basket below.
SP500_URL = ("https://raw.githubusercontent.com/datasets/"
             "s-and-p-500-companies/main/data/constituents.csv")
TICKERS_MAX_AGE_DAYS = 7

# Offline fallback: broad large-cap basket spanning sectors.
FALLBACK_UNIVERSE = [
    # Mega-cap tech / comm
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "ORCL",
    "ADBE", "CRM", "AMD", "INTC", "CSCO", "QCOM", "TXN", "IBM", "NOW", "INTU",
    "AMAT", "MU", "LRCX", "ADI", "PANW", "SNPS", "CDNS", "NFLX", "DIS", "CMCSA",
    "T", "VZ", "TMUS",
    # Financials
    "BRK-B", "JPM", "BAC", "WFC", "GS", "MS", "C", "SCHW", "AXP", "BLK", "SPGI",
    "CB", "PGR", "V", "MA", "PYPL",
    # Health care
    "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "GILD", "CVS", "MDT", "ISRG", "VRTX", "REGN",
    # Consumer
    "WMT", "COST", "HD", "LOW", "TGT", "NKE", "MCD", "SBUX", "PG", "KO", "PEP",
    "PM", "MO", "MDLZ", "CL", "EL", "BKNG", "ABNB",
    # Industrials / materials / energy
    "CAT", "DE", "BA", "GE", "HON", "UPS", "RTX", "LMT", "UNP", "MMM", "EMR",
    "XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC",
    "LIN", "APD", "SHW", "FCX", "NEM",
    # Utilities / real estate / staples
    "NEE", "DUK", "SO", "D", "AEP", "PLD", "AMT", "EQIX", "O", "SPG",
    # High-momentum / growth names
    "SMCI", "ARM", "PLTR", "SNOW", "CRWD", "DDOG", "NET", "SHOP", "UBER",
    "COIN", "MSTR", "DELL", "MRVL", "KLAC", "ASML",
]

CACHE_DIR = Path.home() / ".rs-scanner"
TICKERS_CACHE = CACHE_DIR / "sp500_tickers.json"


def get_universe() -> list:
    """
    Return the current S&P 500 ticker list (cached up to a week), normalized for
    yfinance (e.g. BRK.B -> BRK-B). Falls back to FALLBACK_UNIVERSE on any error.
    """
    try:
        if TICKERS_CACHE.exists():
            obj = json.loads(TICKERS_CACHE.read_text())
            age = (date.today() - date.fromisoformat(obj["fetched"])).days
            if obj.get("tickers") and age <= TICKERS_MAX_AGE_DAYS:
                return obj["tickers"]
    except Exception:
        pass   # corrupt/old cache -> refetch

    try:
        req = urllib.request.Request(SP500_URL, headers={"User-Agent": "Mozilla/5.0"})
        txt = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
        rows = csv.DictReader(io.StringIO(txt))
        tickers = [r["Symbol"].strip().upper().replace(".", "-")
                   for r in rows if r.get("Symbol", "").strip()]
        if len(tickers) >= 400:   # sanity check we got a real list
            try:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                TICKERS_CACHE.write_text(
                    json.dumps({"fetched": date.today().isoformat(), "tickers": tickers}))
            except Exception:
                pass
            return tickers
    except Exception:
        pass

    return FALLBACK_UNIVERSE


def raw_score(daily_close) -> float:
    """
    IBD-style weighted performance score from a *daily* close Series.
    Recent quarter weighted double; higher = stronger. NaN if too little data.
    """
    p = daily_close.dropna()

    def r(n):
        return p.iloc[-1] / p.iloc[-1 - n] if len(p) > n else None

    parts = [(2.0, r(63)), (1.0, r(126)), (1.0, r(189)), (1.0, r(252))]
    parts = [(w, v) for w, v in parts if v is not None]
    if not parts:
        return float("nan")
    return sum(w * v for w, v in parts) / sum(w for w, _ in parts)


def percentile(score: float, scores: dict) -> int:
    """Percentile rank (1-99) of `score` within the universe `scores` dict."""
    vals = [v for v in scores.values() if v == v]   # drop NaN
    if score != score or not vals:
        return 0   # 0 = "n/a"
    rank = sum(1 for v in vals if v <= score)
    pctl = rank / len(vals) * 99.0
    return max(1, min(99, round(pctl)))


def _cache_path(period: str) -> Path:
    return CACHE_DIR / f"scores_{period}_{date.today().isoformat()}.json"


def ensure_scores(period: str) -> dict:
    """
    Return {ticker: raw_score} for the universe, cached per day.
    First call each day downloads the universe (~tens of seconds); later calls
    read the JSON cache instantly.
    """
    path = _cache_path(period)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass   # corrupt cache -> rebuild

    closes = rs.fetch_many(get_universe(), period)
    scores = {t: raw_score(c) for t, c in closes.items()}
    scores = {t: v for t, v in scores.items() if v == v}   # keep finite only

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Clear stale (older-day) caches for this period.
        for old in CACHE_DIR.glob(f"scores_{period}_*.json"):
            if old != path:
                old.unlink(missing_ok=True)
        path.write_text(json.dumps(scores))
    except Exception:
        pass   # caching is best-effort; analysis still works without it

    return scores


def rating(daily_close, period: str) -> int:
    """Convenience: RS Rating for one daily close Series (ensures cache)."""
    return percentile(raw_score(daily_close), ensure_scores(period))
