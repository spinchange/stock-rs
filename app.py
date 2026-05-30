#!/usr/bin/env python
"""
app.py — Native desktop UI for the Relative Strength scanner.

Two tabs in one window:
  - Single chart : type a ticker -> verdict badge + interactive Plotly chart.
  - Leaderboard  : a watchlist -> sortable table ranked by strength;
                   double-click a row to open its chart.

Shared settings (benchmark / period / bars) live in the top bar and apply to
both tabs. Built on PySide6 (Qt) so it packages into a self-contained .exe.

Run during development:
    python app.py
"""

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QObject, Signal, QUrl, QTimer
from PySide6.QtGui import QFont, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QComboBox, QPushButton, QLabel, QTabWidget, QMenu,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

import rs
import scan
import universe

CHART_PATH = Path(tempfile.gettempdir()) / "rs_chart.html"
WATCHLIST_PATH = Path.home() / ".rs-scanner" / "watchlist.json"


# --------------------------------------------------------------------------
# Background workers (keep network/CPU off the UI thread)
# --------------------------------------------------------------------------
class ChartWorker(QObject):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, ticker, benchmark, period, timeframe):
        super().__init__()
        self.args = (ticker, benchmark, period, timeframe)

    def run(self):
        ticker, benchmark, period, timeframe = self.args
        try:
            # Fetch daily closes once; reuse for the chart AND the RS Rating.
            stock_daily = rs.fetch_close(ticker, period)
            bench_daily = rs.fetch_close(benchmark, period)
            res = rs.compute(stock_daily, bench_daily, timeframe)
            fig = rs.build_chart(ticker, benchmark, res)
            html = fig.to_html(include_plotlyjs=True, full_html=True)
            CHART_PATH.write_text(html, encoding="utf-8")
            rating = universe.rating(stock_daily, period)
            self.done.emit({"signals": res["signals"], "rating": rating})
        except SystemExit as e:
            self.failed.emit(str(e))
        except Exception:
            self.failed.emit(traceback.format_exc().strip().splitlines()[-1])


class ScanWorker(QObject):
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, tickers, benchmark, period, timeframe):
        super().__init__()
        self.args = (tickers, benchmark, period, timeframe)

    def run(self):
        tickers, benchmark, period, timeframe = self.args
        try:
            rows = scan.scan_watchlist(tickers, benchmark, period, timeframe)
            self.done.emit(rows)
        except SystemExit as e:
            self.failed.emit(str(e))
        except Exception:
            self.failed.emit(traceback.format_exc().strip().splitlines()[-1])


class MarketWorker(QObject):
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, top_n, benchmark, period, timeframe):
        super().__init__()
        self.args = (top_n, benchmark, period, timeframe)

    def run(self):
        top_n, benchmark, period, timeframe = self.args
        try:
            rows = scan.scan_universe(benchmark, period, timeframe, top_n)
            self.done.emit(rows)
        except SystemExit as e:
            self.failed.emit(str(e))
        except Exception:
            self.failed.emit(traceback.format_exc().strip().splitlines()[-1])


class NumericItem(QTableWidgetItem):
    """Table cell that sorts by an underlying float, not by display text."""
    def __init__(self, text, value):
        super().__init__(text)
        self.value = float(value)
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        if isinstance(other, NumericItem):
            return bool(self.value < other.value)
        return super().__lt__(other)


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Relative Strength Scanner")
        self.resize(1180, 940)
        self._threads = {}   # keep refs alive: name -> (QThread, worker)

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        # --- Shared settings bar -----------------------------------------
        bar = QHBoxLayout(); bar.setSpacing(8)
        self.bench_in = QComboBox(); self.bench_in.addItems(["SPY", "QQQ", "IWM", "DIA", "RSP"])
        self.bench_in.setToolTip("Benchmark to measure against")
        self.period_in = QComboBox(); self.period_in.addItems(["1y", "2y", "3y", "5y"])
        self.period_in.setCurrentText("2y"); self.period_in.setToolTip("How much history to load")
        self.tf_in = QComboBox(); self.tf_in.addItems(["daily", "weekly"])
        self.tf_in.setToolTip("Bar timeframe (weekly = textbook Mansfield)")
        bar.addWidget(QLabel("Benchmark:")); bar.addWidget(self.bench_in)
        bar.addWidget(QLabel("Period:")); bar.addWidget(self.period_in)
        bar.addWidget(QLabel("Bars:")); bar.addWidget(self.tf_in)
        bar.addStretch(1)
        outer.addLayout(bar)

        # Shared leaderboard columns (watchlist + market tabs).
        self.cols = ["Ticker", "Verdict", "RS Rating", "Score", "1m", "3m", "6m", "12m", "RS slope"]

        # --- Tabs ---------------------------------------------------------
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_single_tab(), "Single chart")
        self.tabs.addTab(self._build_leaderboard_tab(), "Watchlist")
        self.tabs.addTab(self._build_market_tab(), "Market leaders")
        outer.addWidget(self.tabs, stretch=1)

        self.setCentralWidget(root)
        self._load_watchlist()
        self.ticker_in.setFocus()

    # ---- Single-chart tab ----
    def _build_single_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(10)

        row = QHBoxLayout(); row.setSpacing(8)
        self.ticker_in = QLineEdit(); self.ticker_in.setPlaceholderText("Ticker  (e.g. NVDA)")
        self.ticker_in.setMaximumWidth(220)
        self.ticker_in.returnPressed.connect(self.run_chart)
        f = self.ticker_in.font(); f.setPointSize(11); self.ticker_in.setFont(f)
        self.run_btn = QPushButton("Run"); self.run_btn.setMinimumWidth(90)
        self.run_btn.clicked.connect(self.run_chart); self.run_btn.setDefault(True)
        row.addWidget(QLabel("Ticker:")); row.addWidget(self.ticker_in)
        row.addWidget(self.run_btn); row.addStretch(1)
        lay.addLayout(row)

        self.verdict = QLabel("Enter a ticker and press Run.")
        self.verdict.setAlignment(Qt.AlignCenter)
        self.verdict.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.verdict.setStyleSheet("padding:8px; border-radius:6px; background:#f1f5f9; color:#334155;")
        lay.addWidget(self.verdict)

        self.view = QWebEngineView()
        self.view.setHtml(
            "<body style='font-family:Segoe UI;color:#94a3b8;display:flex;"
            "align-items:center;justify-content:center;height:100%'>"
            "<h2>Your chart will appear here.</h2></body>"
        )
        lay.addWidget(self.view, stretch=1)
        return w

    # ---- Leaderboard tab ----
    def _build_leaderboard_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(10)

        row = QHBoxLayout(); row.setSpacing(8)
        self.list_in = QLineEdit()
        self.list_in.setPlaceholderText("Tickers, any separator:  NVDA AAPL MSFT, XOM …")
        self.list_in.returnPressed.connect(self.run_scan)
        self.csv_btn = QPushButton("Load CSV…"); self.csv_btn.clicked.connect(self.load_csv)
        self.remove_btn = QPushButton("Remove"); self.remove_btn.clicked.connect(self._remove_selected)
        self.remove_btn.setToolTip("Remove selected row(s) from the watchlist  (Del)")
        self.scan_btn = QPushButton("Scan"); self.scan_btn.setMinimumWidth(90)
        self.scan_btn.clicked.connect(self.run_scan); self.scan_btn.setDefault(True)
        row.addWidget(QLabel("Watchlist:")); row.addWidget(self.list_in, stretch=1)
        row.addWidget(self.csv_btn); row.addWidget(self.remove_btn); row.addWidget(self.scan_btn)
        lay.addLayout(row)

        self.scan_status = QLabel(
            "Type or load tickers, then Scan.  Saved automatically.  "
            "Double-click a row to chart it · select + Del to remove.")
        self.scan_status.setStyleSheet("color:#64748b;")
        lay.addWidget(self.scan_status)

        self.table = self._make_results_table(removable=True)
        lay.addWidget(self.table, stretch=1)
        return w

    def _make_results_table(self, removable):
        """A configured leaderboard table. `removable` adds Del/right-click remove."""
        t = QTableWidget(0, len(self.cols))
        t.setHorizontalHeaderLabels(self.cols)
        t.setSortingEnabled(True)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.ExtendedSelection)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.itemDoubleClicked.connect(self._open_row_chart)
        t.setContextMenuPolicy(Qt.CustomContextMenu)
        t.customContextMenuRequested.connect(
            lambda pos, rm=removable: self._table_menu(pos, rm))
        if removable:
            sc = QShortcut(QKeySequence(Qt.Key_Delete), t)
            sc.setContext(Qt.WidgetShortcut)
            sc.activated.connect(self._remove_selected)
        return t

    # ---- Market-leaders tab ----
    def _build_market_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(10)

        row = QHBoxLayout(); row.setSpacing(8)
        self.topn_in = QComboBox()
        self.topn_in.addItems(["Top 25", "Top 50", "Top 100", "Top 250", "All (~500)"])
        self.topn_in.setCurrentText("Top 50")
        self.topn_in.setToolTip("How many of the strongest names to show")
        self.market_btn = QPushButton("Rank S&P 500"); self.market_btn.setMinimumWidth(130)
        self.market_btn.clicked.connect(self.run_market); self.market_btn.setDefault(True)
        row.addWidget(QLabel("Show:")); row.addWidget(self.topn_in)
        row.addWidget(self.market_btn); row.addStretch(1)
        lay.addLayout(row)

        self.market_status = QLabel(
            "Rank the strongest names in the S&P 500 by RS Rating.  "
            "(double-click a row to chart it)")
        self.market_status.setStyleSheet("color:#64748b;")
        lay.addWidget(self.market_status)

        self.market_table = self._make_results_table(removable=False)
        lay.addWidget(self.market_table, stretch=1)
        return w

    # ---- Single-chart actions ----
    def run_chart(self):
        if "chart" in self._threads:
            return
        ticker = self.ticker_in.text().strip().upper()
        if not ticker:
            self._set_verdict("Type a ticker first.", "#64748b", "#f1f5f9"); return
        self.run_btn.setEnabled(False); self.run_btn.setText("Loading…")
        self._set_verdict(f"Fetching {ticker}…", "#1e3a8a", "#dbeafe")
        self._start("chart", ChartWorker(ticker, self.bench_in.currentText(),
                    self.period_in.currentText(), self.tf_in.currentText()),
                    self._on_chart_done, self._on_chart_failed)

    def _on_chart_done(self, result):
        s = result["signals"]
        rating = result.get("rating", 0)
        badge = s["verdict"]
        if rating:
            badge += f"      ·      RS Rating {rating}/99"
        self._set_verdict(badge, "#ffffff", s["vcolor"])
        self.view.load(QUrl.fromLocalFile(str(CHART_PATH)))
        self._finish("chart"); self.run_btn.setEnabled(True); self.run_btn.setText("Run")

    def _on_chart_failed(self, message):
        self._set_verdict(f"⚠  {message}", "#7f1d1d", "#fee2e2")
        self._finish("chart"); self.run_btn.setEnabled(True); self.run_btn.setText("Run")

    def _set_verdict(self, text, fg, bg):
        self.verdict.setText(text)
        self.verdict.setStyleSheet(f"padding:8px; border-radius:6px; background:{bg}; color:{fg};")

    # ---- Leaderboard actions ----
    def load_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open watchlist", "", "Text/CSV (*.csv *.txt);;All files (*)")
        if not path:
            return
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
        existing = self.list_in.text().strip()
        self.list_in.setText((existing + " " + text) if existing else text)

    def _parse_tickers(self, text):
        raw = text.replace(",", " ").replace(";", " ").replace("\n", " ").replace("\t", " ")
        seen, out = set(), []
        for tok in raw.split():
            t = tok.strip().upper().strip(".")
            # keep plausible symbols only (letters, dots, dashes; <=6 chars)
            if t and len(t) <= 6 and all(c.isalpha() or c in ".-" for c in t) and t not in seen:
                seen.add(t); out.append(t)
        return out

    def run_scan(self):
        if "scan" in self._threads:
            return
        tickers = self._parse_tickers(self.list_in.text())
        if not tickers:
            self.scan_status.setText("No valid tickers found in the watchlist."); return
        # Normalize the field to the cleaned set and persist it.
        self.list_in.setText(" ".join(tickers))
        self._save_watchlist(tickers)
        self.scan_btn.setEnabled(False); self.scan_btn.setText("Scanning…")
        self.scan_status.setText(f"Scanning {len(tickers)} tickers…")
        self._start("scan", ScanWorker(tickers, self.bench_in.currentText(),
                    self.period_in.currentText(), self.tf_in.currentText()),
                    self._on_scan_done, self._on_scan_failed)

    def _on_scan_done(self, rows):
        self._fill_table(rows, self.table)
        ok = sum(1 for r in rows if "error" not in r)
        self.scan_status.setText(
            f"Ranked {ok} of {len(rows)} tickers by RS Rating.  "
            f"Double-click a row to chart it · select + Del to remove.")
        self._finish("scan"); self.scan_btn.setEnabled(True); self.scan_btn.setText("Scan")

    def _on_scan_failed(self, message):
        self.scan_status.setText(f"⚠  {message}")
        self._finish("scan"); self.scan_btn.setEnabled(True); self.scan_btn.setText("Scan")

    # ---- Market-leaders actions ----
    def _top_n(self):
        return {"Top 25": 25, "Top 50": 50, "Top 100": 100,
                "Top 250": 250, "All (~500)": None}[self.topn_in.currentText()]

    def run_market(self):
        if "market" in self._threads:
            return
        self.market_btn.setEnabled(False); self.market_btn.setText("Ranking…")
        self.market_status.setText(
            "Ranking the S&P 500 by RS Rating…  "
            "(first scan of the day downloads the universe, ~20s)")
        self._start("market", MarketWorker(self._top_n(), self.bench_in.currentText(),
                    self.period_in.currentText(), self.tf_in.currentText()),
                    self._on_market_done, self._on_market_failed)

    def _on_market_done(self, rows):
        self._fill_table(rows, self.market_table)
        ok = sum(1 for r in rows if "error" not in r)
        self.market_status.setText(
            f"Top {ok} S&P 500 names by RS Rating, vs {self.bench_in.currentText()}.  "
            f"(double-click a row to chart it)")
        self._finish("market"); self.market_btn.setEnabled(True); self.market_btn.setText("Rank S&P 500")

    def _on_market_failed(self, message):
        self.market_status.setText(f"⚠  {message}")
        self._finish("market"); self.market_btn.setEnabled(True); self.market_btn.setText("Rank S&P 500")

    def _col(self, name):
        return self.cols.index(name)

    def _signed_item(self, v):
        """A right-aligned, green/red, NaN-aware percent cell that sorts numerically."""
        nan = v != v
        item = NumericItem("—" if nan else f"{v:+.1f}%", -1e9 if nan else v)
        if not nan:
            item.setForeground(QColor("#16a34a") if v >= 0 else QColor("#dc2626"))
        return item

    def _fill_table(self, rows, table):
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            tick = QTableWidgetItem(r["ticker"]); tick.setFont(QFont("Segoe UI", 10, QFont.Bold))
            table.setItem(i, self._col("Ticker"), tick)
            if "error" in r:
                err = QTableWidgetItem(f"— {r['error']}"); err.setForeground(QColor("#94a3b8"))
                table.setItem(i, self._col("Verdict"), err)
                for name in self.cols[2:]:
                    table.setItem(i, self._col(name), NumericItem("—", float("-inf")))
                continue
            verdict = QTableWidgetItem(r["verdict"])
            verdict.setForeground(QColor(r["vcolor"])); verdict.setFont(QFont("Segoe UI", 10, QFont.Bold))
            table.setItem(i, self._col("Verdict"), verdict)

            rating = r.get("rating", 0)
            rcolor = "#16a34a" if rating >= 80 else "#dc2626" if (rating and rating <= 20) else "#334155"
            ritem = NumericItem("—" if not rating else str(rating), -1 if not rating else rating)
            ritem.setForeground(QColor(rcolor)); ritem.setFont(QFont("Segoe UI", 10, QFont.Bold))
            table.setItem(i, self._col("RS Rating"), ritem)

            table.setItem(i, self._col("Score"), NumericItem(f"{r['score']:+.1f}", r["score"]))
            ex = r["excess"]
            for key in ("1m", "3m", "6m", "12m"):
                table.setItem(i, self._col(key), self._signed_item(ex[key]))
            table.setItem(i, self._col("RS slope"), self._signed_item(r["slope"]))
        table.setSortingEnabled(True)
        table.sortItems(self._col("RS Rating"), Qt.DescendingOrder)   # strongest first

    def _open_row_chart(self, item):
        table = item.tableWidget()
        ticker = table.item(item.row(), 0).text()
        self.ticker_in.setText(ticker)
        self.tabs.setCurrentIndex(0)
        self.run_chart()

    # ---- watchlist persistence + removal ----
    def _load_watchlist(self):
        try:
            tickers = json.loads(WATCHLIST_PATH.read_text()).get("tickers", [])
            if tickers:
                self.list_in.setText(" ".join(tickers))
        except Exception:
            pass   # no saved list yet, or unreadable -> start empty

    def _save_watchlist(self, tickers):
        try:
            WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
            WATCHLIST_PATH.write_text(json.dumps({"tickers": tickers}))
        except Exception:
            pass   # best-effort

    def _selected_tickers(self):
        rows = {ix.row() for ix in self.table.selectedIndexes()}
        return {self.table.item(r, 0).text() for r in rows if self.table.item(r, 0)}

    def _remove_selected(self):
        drop = self._selected_tickers()
        if not drop:
            return
        remaining = [t for t in self._parse_tickers(self.list_in.text()) if t not in drop]
        self.list_in.setText(" ".join(remaining))
        self._save_watchlist(remaining)
        for r in sorted({ix.row() for ix in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)
        self.scan_status.setText(
            f"Removed {len(drop)} from watchlist: {', '.join(sorted(drop))}.")

    def _table_menu(self, pos, removable):
        table = self.sender()
        item = table.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        act_chart = menu.addAction("Open chart")
        act_remove = menu.addAction("Remove from watchlist") if removable else None
        chosen = menu.exec(table.viewport().mapToGlobal(pos))
        if chosen == act_chart:
            self._open_row_chart(item)
        elif removable and chosen == act_remove:
            self._remove_selected()

    # ---- shared thread plumbing ----
    def _start(self, name, worker, on_done, on_failed):
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(on_done)
        worker.failed.connect(on_failed)
        self._threads[name] = (thread, worker)
        thread.start()

    def _finish(self, name):
        pair = self._threads.pop(name, None)
        if pair:
            thread, _ = pair
            thread.quit(); thread.wait()


def _selftest():
    """Headless check of the data path (yfinance -> compute -> plotly inline).
    Used to validate the *packaged* build without needing the GUI. Writes a
    result line to a log file since --windowed builds have no console."""
    log = Path(tempfile.gettempdir()) / "rs_selftest.log"
    try:
        res = rs.analyze("AAPL", "SPY", "1y", "daily")
        html = rs.build_chart("AAPL", "SPY", res).to_html(include_plotlyjs=True, full_html=True)
        rating = universe.rating(rs.fetch_close("AAPL", "1y"), "1y")
        log.write_text(f"OK verdict={res['signals']['verdict']} "
                       f"html_bytes={len(html)} rating={rating}\n")
    except Exception:
        log.write_text("FAIL\n" + traceback.format_exc())


def _webtest():
    """Headless render check: load a real chart into QWebEngineView and confirm
    Plotly actually drew it. Validates the *bundled* WebEngine + its resources
    (catches a broken/over-pruned Chromium bundle that a data-only test misses)."""
    log = Path(tempfile.gettempdir()) / "rs_webtest.log"
    try:
        res = rs.analyze("AAPL", "SPY", "1y", "daily")
        html = rs.build_chart("AAPL", "SPY", res).to_html(include_plotlyjs=True, full_html=True)
        page_path = Path(tempfile.gettempdir()) / "rs_webtest.html"
        page_path.write_text(html, encoding="utf-8")
    except Exception:
        log.write_text("FAIL build\n" + traceback.format_exc())
        return

    app = QApplication(sys.argv)
    view = QWebEngineView()
    state = {"done": False}

    def finish(msg):
        if not state["done"]:
            state["done"] = True
            log.write_text(msg + "\n")
            app.quit()

    def on_load(ok):
        if not ok:
            finish("FAIL load=False"); return
        # Give Plotly a beat to draw, then count its rendered containers.
        QTimer.singleShot(800, lambda: view.page().runJavaScript(
            "document.querySelectorAll('.plotly').length",
            lambda n: finish(f"OK plotly_nodes={n}" if n else "FAIL plotly_nodes=0")))

    view.loadFinished.connect(on_load)
    view.load(QUrl.fromLocalFile(str(page_path)))
    QTimer.singleShot(25000, lambda: finish("FAIL timeout"))
    view.resize(900, 700); view.show()
    app.exec()


def main():
    if os.environ.get("RS_SELFTEST"):
        _selftest()
        return
    if os.environ.get("RS_WEBTEST"):
        _webtest()
        return
    app = QApplication(sys.argv)
    app.setApplicationName("Relative Strength Scanner")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
