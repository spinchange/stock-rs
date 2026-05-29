# Relative Strength Scanner

A desktop stock-chart app for checking relative strength versus a benchmark and ranking leaders by RS Rating.

## What it does

- Chart a ticker against a benchmark such as `SPY`, `QQQ`, `IWM`, `DIA`, or `RSP`
- Show a relative-strength verdict and RS slope
- Rank a custom watchlist by strength
- Rank the strongest names in the S&P 500 by RS Rating
- Render interactive Plotly charts inside a native PySide6 desktop UI

## Project files

- `app.py` — desktop UI
- `rs.py` — core relative-strength engine and CLI
- `scan.py` — watchlist and market scan logic
- `universe.py` — RS Rating / S&P 500 universe logic
- `RS.spec` — PyInstaller packaging spec

## Local setup

```bash
python -m pip install -r requirements.txt
python app.py
```

## CLI usage

```bash
python rs.py NVDA --benchmark SPY --period 1y --timeframe daily
python rs.py NVDA --benchmark QQQ --period 3y --timeframe weekly --no-open
```

## Build a Windows executable

```bash
pyinstaller RS.spec
```

The packaged executable is intentionally not committed here because the generated `dist/` folder is very large. Rebuild it locally when needed.
