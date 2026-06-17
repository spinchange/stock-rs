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
- `RS.spec` — PyInstaller packaging spec (excludes unused Qt modules / heavy deps)
- `build.ps1` — one-command build: PyInstaller + English-only translation prune

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

```powershell
pwsh -File build.ps1
```

This builds from `RS.spec` (which excludes unused Qt modules and heavy unused
packages) and then prunes the bundled Qt/WebEngine translations to English,
producing a self-contained `dist\RS\` folder. Run `RS.exe` inside it, or zip the
folder to distribute. Expect ~625 MB — the floor is Qt WebEngine's bundled
Chromium engine, which can't be removed from an embedded-browser app.

To validate a packaged build headlessly, set `RS_SELFTEST=1` (data path) or
`RS_WEBTEST=1` (WebEngine actually renders a chart) when launching `RS.exe`; each
writes a result line to `rs_selftest.log` / `rs_webtest.log` in the temp dir.

The `dist/` folder is large and git-ignored, so it is not committed — rebuild locally.
