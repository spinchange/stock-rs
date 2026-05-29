#!/usr/bin/env python
"""
rs.py — Relative Strength scanner (core engine + CLI).

Given a stock ticker, show whether it is STRONG (outperforming the broader
market) and GETTING STRONGER (that outperformance is accelerating).

Usage:
    python rs.py NVDA
    python rs.py NVDA --benchmark QQQ --period 3y --timeframe weekly
    python rs.py NVDA --no-open

Core idea — the Relative Strength (RS) line:
    RS = stock_price / benchmark_price
    - RS rising  => stock is beating the market (leadership)
    - RS falling => stock is lagging the market

Timeframe note: the Mansfield RS oscillator is traditionally a *weekly*
indicator (RS vs its 52-week average), so --timeframe weekly is the
textbook-correct long-term read; daily is the zoomed-in view.
"""

import argparse
import webbrowser
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from plotly.subplots import make_subplots

GREEN = "#16a34a"
RED = "#dc2626"
GREY = "#64748b"
BLUE = "#2563eb"

# Per-timeframe parameters. "bars" are in that timeframe's units (days/weeks).
TIMEFRAMES = {
    "daily": dict(
        resample=None,
        price_ma=(50, 150, 200),
        rs_sma=50,
        mansfield=200,
        lookback={"1m": 21, "3m": 63, "6m": 126, "12m": 252},
        slope_short=21, slope_long=63,
        unit="d",
    ),
    "weekly": dict(
        resample="W-FRI",
        price_ma=(10, 30, 40),
        rs_sma=10,
        mansfield=52,
        lookback={"1m": 4, "3m": 13, "6m": 26, "12m": 52},
        slope_short=4, slope_long=13,
        unit="w",
    ),
}


def fetch_close(ticker: str, period: str) -> pd.Series:
    """Download adjusted daily closing prices as a clean Series."""
    df = yf.download(
        ticker, period=period, interval="1d",
        auto_adjust=True, progress=False, multi_level_index=False,
    )
    if df is None or df.empty:
        raise SystemExit(f"No data returned for '{ticker}'. Check the symbol.")
    close = df["Close"].dropna()
    close.name = ticker
    return close


def fetch_many(tickers, period: str) -> dict:
    """
    Download daily closes for many tickers in one call.
    Returns {ticker: close Series}, silently omitting any that returned nothing.
    """
    tickers = list(dict.fromkeys(t.upper() for t in tickers))  # dedupe, keep order
    if not tickers:
        return {}
    df = yf.download(
        tickers, period=period, interval="1d",
        auto_adjust=True, progress=False, threads=True,
    )
    if df is None or df.empty:
        return {}

    out = {}
    if isinstance(df.columns, pd.MultiIndex):       # multiple tickers
        close = df["Close"]
        for t in tickers:
            if t in close.columns:
                s = close[t].dropna()
                if not s.empty:
                    s.name = t
                    out[t] = s
    else:                                           # single-ticker shape
        s = df["Close"].dropna()
        if not s.empty:
            s.name = tickers[0]
            out[tickers[0]] = s
    return out


def resample_close(close: pd.Series, timeframe: str) -> pd.Series:
    """Resample a daily close Series to the requested timeframe."""
    rule = TIMEFRAMES[timeframe]["resample"]
    if rule:
        close = close.resample(rule).last().dropna()
    return close


def pct(series: pd.Series, lookback: int) -> float:
    """Percent change over the last `lookback` bars."""
    if len(series) <= lookback:
        return float("nan")
    return (series.iloc[-1] / series.iloc[-1 - lookback] - 1.0) * 100.0


def compute(stock_close: pd.Series, bench_close: pd.Series, timeframe: str) -> dict:
    """
    Core analysis on two daily price Series. Resamples to `timeframe`, builds
    the RS line + signals, and returns everything the chart and the leaderboard
    need. No network, no plotting — pure computation so it's reusable in batch.
    """
    tf = TIMEFRAMES[timeframe]
    stock = resample_close(stock_close, timeframe)
    bench = resample_close(bench_close, timeframe)

    data = pd.concat([stock, bench], axis=1, join="inner").dropna()
    data.columns = ["stock", "bench"]
    if len(data) < 30:
        raise SystemExit("Not enough overlapping history to analyze.")

    # Relative strength line, normalized so the first bar = 100.
    rs = data["stock"] / data["bench"]
    rs = rs / rs.iloc[0] * 100.0
    rs_sma = rs.rolling(tf["rs_sma"]).mean()

    # Mansfield-style oscillator: RS relative to its long-run average.
    long_win = min(tf["mansfield"], max(20, len(rs) // 3))
    rs_long = rs.rolling(long_win).mean()
    mansfield = (rs / rs_long - 1.0) * 100.0

    # Price moving averages (windows depend on timeframe).
    price = data["stock"]
    ma = {w: price.rolling(w).mean() for w in tf["price_ma"]}

    # --- Signals -----------------------------------------------------------
    lb = tf["lookback"]
    excess = {  # stock return minus benchmark return, per horizon
        k: pct(data["stock"], n) - pct(data["bench"], n) for k, n in lb.items()
    }
    rs_above_trend = (
        bool(rs.iloc[-1] > rs_sma.iloc[-1]) if not pd.isna(rs_sma.iloc[-1]) else False
    )
    rs_high = rs.tail(lb["12m"]).max()
    near_rs_high = bool(rs.iloc[-1] >= 0.97 * rs_high)

    slope_short = pct(rs, tf["slope_short"])
    slope_long = pct(rs, tf["slope_long"])
    accelerating = bool(slope_short > 0 and slope_short >= slope_long / 3)

    strong = rs_above_trend and (excess["3m"] > 0) and (excess["6m"] > 0)
    strengthening = accelerating and slope_short > 0

    if strong and strengthening:
        verdict, vcolor = "STRONG & STRENGTHENING", GREEN
    elif strong:
        verdict, vcolor = "STRONG, but momentum cooling", "#65a30d"
    elif not strong and strengthening:
        verdict, vcolor = "LAGGING, but improving", "#d97706"
    else:
        verdict, vcolor = "WEAK / LAGGING the market", RED

    signals = {
        "verdict": verdict,
        "vcolor": vcolor,
        "excess": excess,
        "rs_above_trend": rs_above_trend,
        "near_rs_high": near_rs_high,
        "slope_short": slope_short,
        "slope_long": slope_long,
    }
    return dict(
        data=data, rs=rs, rs_sma=rs_sma, mansfield=mansfield, ma=ma,
        signals=signals, timeframe=timeframe,
    )


def analyze(ticker: str, benchmark: str, period: str, timeframe: str = "daily") -> dict:
    """Fetch + compute for a single ticker. Returns the dict from compute()."""
    stock = fetch_close(ticker, period)
    bench = fetch_close(benchmark, period)
    return compute(stock, bench, timeframe)


def build_chart(ticker, benchmark, res):
    """Build the 3-panel Plotly figure from a compute() result dict."""
    data, rs, rs_sma = res["data"], res["rs"], res["rs_sma"]
    mansfield, ma, signals = res["mansfield"], res["ma"], res["signals"]
    tf = TIMEFRAMES[res["timeframe"]]
    unit = tf["unit"]
    ma_windows = sorted(ma.keys())

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        row_heights=[0.46, 0.30, 0.24],
        subplot_titles=(
            f"{ticker} price + moving averages ({res['timeframe']})",
            f"Relative Strength: {ticker} vs {benchmark} (rising = beating the market)",
            f"Mansfield RS oscillator (above 0 = leading the market)",
        ),
    )

    # Panel 1 — price + MAs
    fig.add_trace(go.Scatter(x=data.index, y=data["stock"], name=ticker,
                             line=dict(color="#0f172a", width=1.6)), row=1, col=1)
    for w, color in zip(ma_windows, ("#f59e0b", "#8b5cf6", "#0ea5e9")):
        fig.add_trace(go.Scatter(x=data.index, y=ma[w], name=f"MA{w}{unit}",
                                 line=dict(color=color, width=1)), row=1, col=1)

    # Panel 2 — RS line + its average, shaded by above/below trend
    fig.add_trace(go.Scatter(x=rs.index, y=rs, name="RS line",
                             line=dict(color=BLUE, width=1.8)), row=2, col=1)
    fig.add_trace(go.Scatter(x=rs_sma.index, y=rs_sma, name=f"RS {tf['rs_sma']}{unit} avg",
                             line=dict(color=GREY, width=1, dash="dot")), row=2, col=1)

    # Panel 3 — Mansfield oscillator histogram (green/red around 0)
    colors = [GREEN if v >= 0 else RED for v in mansfield.fillna(0)]
    fig.add_trace(go.Bar(x=mansfield.index, y=mansfield, name="Mansfield RS",
                         marker_color=colors, showlegend=False), row=3, col=1)
    fig.add_hline(y=0, line=dict(color=GREY, width=1), row=3, col=1)

    ex = signals["excess"]
    subtitle = (
        f"Excess return vs {benchmark} &nbsp;|&nbsp; "
        f"1m {ex['1m']:+.1f}% &nbsp; 3m {ex['3m']:+.1f}% &nbsp; "
        f"6m {ex['6m']:+.1f}% &nbsp; 12m {ex['12m']:+.1f}%"
    )

    fig.update_layout(
        template="plotly_white",
        title=dict(
            text=(f"<b>{ticker}</b> &nbsp; "
                  f"<span style='color:{signals['vcolor']}'>"
                  f"&#9632; {signals['verdict']}</span><br>"
                  f"<span style='font-size:13px;color:{GREY}'>{subtitle}</span>"),
            x=0.5, xanchor="center",
        ),
        height=900, hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(t=120, b=40, l=60, r=30),
    )
    return fig


def main():
    p = argparse.ArgumentParser(description="Relative Strength scanner.")
    p.add_argument("ticker", help="Stock symbol, e.g. NVDA")
    p.add_argument("--benchmark", default="SPY", help="Benchmark symbol (default SPY)")
    p.add_argument("--period", default="2y", help="History window (default 2y)")
    p.add_argument("--timeframe", default="daily", choices=("daily", "weekly"),
                   help="Bar timeframe (default daily)")
    p.add_argument("--no-open", action="store_true", help="Write HTML but don't open browser")
    args = p.parse_args()

    ticker = args.ticker.upper()
    benchmark = args.benchmark.upper()

    res = analyze(ticker, benchmark, args.period, args.timeframe)
    fig = build_chart(ticker, benchmark, res)

    out = Path(__file__).parent / f"rs_{ticker}.html"
    fig.write_html(str(out), include_plotlyjs="cdn")

    s = res["signals"]
    ex = s["excess"]
    print(f"\n{ticker} vs {benchmark} ({args.timeframe})  ->  {s['verdict']}")
    print(f"  Excess return: 1m {ex['1m']:+.1f}%  3m {ex['3m']:+.1f}%  "
          f"6m {ex['6m']:+.1f}%  12m {ex['12m']:+.1f}%")
    print(f"  RS above its trend : {s['rs_above_trend']}")
    print(f"  Near 1-yr RS high  : {s['near_rs_high']}")
    print(f"  RS slope short/long: {s['slope_short']:+.1f}% / {s['slope_long']:+.1f}%")
    print(f"  Chart: {out}")

    if not args.no_open:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
