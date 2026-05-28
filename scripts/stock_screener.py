#!/usr/bin/env python3
"""
US Stock Daily Screener
=======================
Criteria
  1. Bullish EMA alignment: EMA5 > EMA10 > EMA20 > EMA50 > EMA200
  2. YTD gain > 20 %  (configurable)
  3. Stock belongs to one of the top-performing sectors YTD

Run:
  python3 stock_screener.py
  python3 stock_screener.py --ytd 30 --sectors 3    # stricter filters
  python3 stock_screener.py --html                   # also save HTML report
"""

import sys
import json
import argparse
import warnings
from datetime import datetime, date
from pathlib import Path

warnings.filterwarnings("ignore")

try:
    import yfinance as yf
    import pandas as pd
    from tabulate import tabulate
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Run: pip install -r requirements.txt")
    sys.exit(1)

# ── Default configuration ──────────────────────────────────────────────────────

DEFAULTS = {
    "ytd_min_pct":       20.0,   # min YTD gain %
    "top_sector_count":   4,      # leading sectors to include
    "ema_periods":       [5, 10, 20, 50, 200],
    "volume_avg_days":    20,
    "min_price":          5.0,    # exclude penny stocks
    "min_avg_volume": 500_000,    # exclude illiquid names
}

# Sector ETFs for YTD ranking
SECTOR_ETFS = {
    "Technology":       "XLK",
    "Healthcare":       "XLV",
    "Financials":       "XLF",
    "Consumer Discret": "XLY",
    "Industrials":      "XLI",
    "Energy":           "XLE",
    "Materials":        "XLB",
    "Utilities":        "XLU",
    "Real Estate":      "XLRE",
    "Consumer Staples": "XLP",
    "Communication":    "XLC",
}

# Liquid, investable stocks per sector
SECTOR_STOCKS = {
    "Technology": [
        "NVDA","MSFT","AAPL","AVGO","ORCL","AMD","QCOM","TXN","AMAT","LRCX",
        "KLAC","MU","SNPS","CDNS","ADI","MRVL","FTNT","PANW","CRWD","ZS",
        "NOW","PLTR","ADBE","CRM","INTU","SNOW","NET","DDOG","MDB","NTNX",
        "SMCI","ARM","DELL","PSTG","WDAY","VEEV","HUBS","BILL","GTLB","APP",
    ],
    "Healthcare": [
        "LLY","UNH","JNJ","ABBV","MRK","TMO","DHR","ABT","ISRG","SYK",
        "ELV","CI","HUM","MDT","BSX","ZBH","BAX","BDX","REGN","BIIB",
        "VRTX","GILD","AMGN","MRNA","ILMN","IDXX","IQV","CRL","A","WAT",
    ],
    "Financials": [
        "BRK-B","JPM","V","MA","BAC","WFC","GS","MS","AXP","BLK",
        "SPGI","MCO","ICE","CME","CB","PGR","TRV","ALL","MET","PRU",
        "USB","PNC","COF","DFS","SCHW","IBKR","RJF","STT","BK","NTRS",
    ],
    "Consumer Discret": [
        "AMZN","TSLA","HD","MCD","NKE","SBUX","LOW","TJX","BKNG","ABNB",
        "LVS","MGM","RCL","CCL","NCLH","EXPE","ROST","BBWI","TPR","RL",
        "PHM","DHI","LEN","TOL","CVNA","KMX","AN","PAG","LAD","AAP",
    ],
    "Industrials": [
        "CAT","DE","RTX","HON","UPS","BA","GE","LMT","NOC","GD",
        "ETN","EMR","ROK","PH","ITW","MMM","SWK","GWW","FAST","RSG",
        "WM","VRSK","CPRT","CTAS","NSC","UNP","CSX","XPO","ODFL","JBHT",
    ],
    "Energy": [
        "XOM","CVX","COP","EOG","SLB","MPC","VLO","PSX","OXY","PXD",
        "DVN","FANG","HES","APA","HAL","BKR","CTRA","EQT","AR","RRC",
    ],
    "Materials": [
        "LIN","APD","SHW","ECL","NEM","FCX","NUE","STLD","CF","MOS",
        "ALB","BALL","IP","PKG","SEE","SON","RPM","PPG","EMN","CE",
    ],
    "Communication": [
        "META","GOOG","GOOGL","NFLX","DIS","CMCSA","T","VZ","TMUS",
        "CHTR","WBD","PARA","FOX","FOXA","OMC","IPG","TTWO","EA","ATVI",
    ],
    "Consumer Staples": [
        "PG","KO","PEP","COST","WMT","PM","MO","CL","KMB","GIS",
        "K","CPB","SJM","HRL","TSN","CAG","MKC","CHD","CLX","EL",
    ],
    "Utilities": [
        "NEE","SO","DUK","AEP","D","EXC","XEL","WEC","ES","ETR",
        "FE","PPL","CMS","NI","AES","LNT","PNW","IDA","AVA","NWE",
    ],
    "Real Estate": [
        "PLD","AMT","EQIX","CCI","PSA","WELL","DLR","O","SPG","EQR",
        "AVB","ESS","MAA","UDR","CPT","VTR","PEAK","ARE","BXP","SLG",
    ],
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def ytd_start_str() -> str:
    return f"{date.today().year}-01-01"


def pct_change(new_val: float, old_val: float) -> float:
    if old_val and old_val != 0:
        return (new_val - old_val) / abs(old_val) * 100
    return 0.0


def compute_bullish_ema(closes: "pd.Series", periods: list[int]) -> tuple[bool, dict]:
    """
    Returns (is_bullish_aligned, ema_dict).
    Bullish = EMA[shorter] > EMA[longer] for every adjacent pair.
    """
    if len(closes) < max(periods):
        return False, {}
    emas = {p: float(closes.ewm(span=p, adjust=False).mean().iloc[-1]) for p in periods}
    sorted_p = sorted(periods)
    aligned = all(emas[sorted_p[i]] > emas[sorted_p[i + 1]] for i in range(len(sorted_p) - 1))
    return aligned, emas


def fmt_volume(v) -> str:
    if v is None:
        return "N/A"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    return f"{v / 1_000:.0f}K"


# ANSI colours
def _c(t, code): return f"\033[{code}m{t}\033[0m"
def green(t):   return _c(t, "92")
def yellow(t):  return _c(t, "93")
def cyan(t):    return _c(t, "96")
def bold(t):    return _c(t, "1")

# ── Data fetching ──────────────────────────────────────────────────────────────

def rank_sectors(cfg: dict) -> list[tuple[str, float]]:
    print("  Fetching sector ETF data...")
    tickers = list(SECTOR_ETFS.values())
    data = yf.download(tickers, start=ytd_start_str(), progress=False, auto_adjust=True)

    if data.empty:
        print("  WARNING: Could not fetch sector data.")
        return []

    close_df = data["Close"] if "Close" in data else data
    results = []
    for sector, etf in SECTOR_ETFS.items():
        if etf not in close_df.columns:
            continue
        series = close_df[etf].dropna()
        if len(series) < 2:
            continue
        gain = pct_change(float(series.iloc[-1]), float(series.iloc[0]))
        results.append((sector, gain))

    return sorted(results, key=lambda x: x[1], reverse=True)


def screen_stocks(leading_sectors: list[str], cfg: dict) -> list[dict]:
    candidates = []
    for sector in leading_sectors:
        candidates.extend(SECTOR_STOCKS.get(sector, []))
    candidates = list(dict.fromkeys(candidates))  # deduplicate, keep order

    total = len(candidates)
    print(f"  Scanning {total} stocks in {len(leading_sectors)} leading sectors...")

    hist_start  = f"{date.today().year - 1}-01-01"  # need ~1 year for EMA200
    ytd_start   = ytd_start_str()
    batch_size  = 50
    results     = []

    for batch_idx in range(0, total, batch_size):
        batch = candidates[batch_idx : batch_idx + batch_size]
        pct_done = min(batch_idx + batch_size, total)
        print(f"    Processing {pct_done}/{total} tickers...", end="\r")

        try:
            raw = yf.download(batch, start=hist_start, progress=False, auto_adjust=True)
        except Exception as exc:
            print(f"\n  Warning: batch download failed – {exc}")
            continue

        close_df  = raw.get("Close",  raw if isinstance(raw, pd.DataFrame) else raw)
        volume_df = raw.get("Volume", None)

        if isinstance(close_df, pd.Series):
            close_df  = close_df.to_frame(batch[0])
        if volume_df is not None and isinstance(volume_df, pd.Series):
            volume_df = volume_df.to_frame(batch[0])

        for ticker in batch:
            try:
                if ticker not in close_df.columns:
                    continue

                closes = close_df[ticker].dropna()
                if len(closes) < max(cfg["ema_periods"]) + 1:
                    continue

                current_price = float(closes.iloc[-1])
                if current_price < cfg["min_price"]:
                    continue

                # ── YTD gain ──────────────────────────────────────
                ytd_slice = closes[closes.index >= ytd_start]
                if ytd_slice.empty:
                    continue
                ytd_gain = pct_change(current_price, float(ytd_slice.iloc[0]))
                if ytd_gain < cfg["ytd_min_pct"]:
                    continue

                # ── Volume filter ─────────────────────────────────
                avg_vol = None
                if volume_df is not None and ticker in volume_df.columns:
                    vols = volume_df[ticker].dropna()
                    if len(vols) >= cfg["volume_avg_days"]:
                        avg_vol = float(vols.iloc[-cfg["volume_avg_days"]:].mean())
                        if avg_vol < cfg["min_avg_volume"]:
                            continue

                # ── EMA alignment ─────────────────────────────────
                is_bullish, emas = compute_bullish_ema(closes, cfg["ema_periods"])
                if not is_bullish:
                    continue

                sector = next(
                    (s for s in leading_sectors if ticker in SECTOR_STOCKS.get(s, [])),
                    "Unknown",
                )

                # ── RSI14 (bonus context) ─────────────────────────
                delta  = closes.diff()
                gain_s = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
                loss_s = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
                rsi    = 100 - (100 / (1 + gain_s / loss_s.replace(0, float("nan"))))
                rsi14  = float(rsi.iloc[-1]) if not rsi.empty else None

                results.append({
                    "ticker":   ticker,
                    "price":    round(current_price, 2),
                    "ytd_pct":  round(ytd_gain, 2),
                    "rsi14":    round(rsi14, 1) if rsi14 else None,
                    "sector":   sector,
                    "avg_vol":  avg_vol,
                    "ema5":     emas.get(5),
                    "ema10":    emas.get(10),
                    "ema20":    emas.get(20),
                    "ema50":    emas.get(50),
                    "ema200":   emas.get(200),
                })

            except Exception:
                continue

    print(" " * 60, end="\r")
    return sorted(results, key=lambda x: x["ytd_pct"], reverse=True)


# ── Reports ────────────────────────────────────────────────────────────────────

def print_terminal_report(sector_ranking, leading_sectors, results, cfg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    w = 72
    print()
    print(bold(cyan("═" * w)))
    print(bold(cyan(f"  US STOCK DAILY SCREENER  |  {now}")))
    print(bold(cyan("═" * w)))

    # Sector table
    print(bold("\n  SECTOR RANKING (YTD)"))
    for sector, gain in sector_ranking:
        is_lead = sector in leading_sectors
        star  = "★" if is_lead else " "
        g_str = (green if gain > 0 else lambda x: x)(f"{gain:+.1f}%")
        name  = bold(f"  {star} {sector}") if is_lead else f"    {sector}"
        print(f"{name:<30}  {g_str}")

    # Screened stocks
    count = len(results)
    print(bold(f"\n  SCREENED STOCKS  —  {count} passed all filters"))
    print(f"  ▸ Bullish EMA (5>10>20>50>200)  ▸ YTD >{cfg['ytd_min_pct']:.0f}%"
          f"  ▸ Top-{cfg['top_sector_count']} sectors")
    print("  " + "─" * (w - 2))

    if not results:
        print(yellow("  No stocks passed all filters today."))
    else:
        headers = ["#", "Ticker", "Price", "YTD %", "RSI", "Sector", "Avg Vol", "vs EMA20"]
        rows = []
        for i, s in enumerate(results, 1):
            ytd_str = f"{s['ytd_pct']:+.1f}%"
            ema20   = s.get("ema20")
            vs_ema  = (f"+{(s['price'] - ema20) / ema20 * 100:.1f}%"
                       if ema20 else "─")
            rsi_str = f"{s['rsi14']:.0f}" if s["rsi14"] else "─"
            rows.append([
                i,
                s["ticker"],
                f"${s['price']:.2f}",
                ytd_str,
                rsi_str,
                s["sector"][:16],
                fmt_volume(s["avg_vol"]),
                vs_ema,
            ])
        print(tabulate(rows, headers=headers, tablefmt="simple"))

    print()
    print(bold(cyan("═" * w)))
    print("  Quick guide:")
    print("    ▸ Focus on stocks with RSI 50–70 (momentum, not overbought)")
    print("    ▸ Price > EMA20 by +3–8 % = healthy pullback entry zone")
    print("    ▸ Validate with volume spike on breakout day")
    print(bold(cyan("═" * w)))
    print()


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stock Screener — {date}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #0d1117; color: #c9d1d9; margin: 0; padding: 24px; }}
  h1   {{ color: #58a6ff; font-size: 1.4rem; border-bottom: 1px solid #30363d; padding-bottom: 8px; }}
  h2   {{ color: #79c0ff; font-size: 1rem; margin-top: 24px; }}
  .meta {{ color: #8b949e; font-size: 0.85rem; margin-bottom: 16px; }}
  .criteria {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px;
               padding: 10px 16px; display: inline-block; font-size: 0.85rem; color: #8b949e; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 0.9rem; }}
  th    {{ text-align: left; padding: 8px 12px; background: #161b22;
           color: #8b949e; border-bottom: 1px solid #30363d; font-weight: 600; }}
  td    {{ padding: 8px 12px; border-bottom: 1px solid #21262d; }}
  tr:hover td {{ background: #161b22; }}
  .ticker {{ font-weight: 700; color: #58a6ff; }}
  .up     {{ color: #3fb950; font-weight: 600; }}
  .star   {{ color: #d29922; }}
  .sector-lead {{ font-weight: 600; color: #e3b341; }}
  .badge  {{ display: inline-block; padding: 2px 8px; border-radius: 12px;
             background: #1f6feb33; color: #58a6ff; font-size: 0.78rem; }}
  .tv-btn {{ display: inline-flex; align-items: center; gap: 6px; margin-top: 12px;
             padding: 8px 16px; background: #1565c0; color: #fff; border: none;
             border-radius: 6px; font-size: 0.9rem; font-weight: 600; cursor: pointer;
             text-decoration: none; }}
  .tv-btn:hover {{ background: #1976d2; }}
</style>
</head>
<body>
<h1>📊 US Stock Daily Screener</h1>
<p class="meta">Generated: {datetime} &nbsp;|&nbsp; {count} stocks passed</p>
<div class="criteria">
  Bullish EMA (5 &gt; 10 &gt; 20 &gt; 50 &gt; 200) &nbsp;·&nbsp;
  YTD &gt; {ytd_min}% &nbsp;·&nbsp;
  Top-{top_n} sectors
</div>
<br>
<a class="tv-btn" href="{watchlist_filename}" download>
  ⬇ Download TradingView Watchlist
</a>
<span style="color:#8b949e; font-size:0.8rem; margin-left:12px;">
  TV → Watchlist panel → ⋮ → Import watchlist → select file
</span>

<h2>Sector Ranking (YTD)</h2>
<table>
  <tr><th>Sector</th><th>YTD %</th><th>Role</th></tr>
  {sector_rows}
</table>

<h2>Screened Stocks</h2>
<table>
  <tr>
    <th>#</th><th>Ticker</th><th>Price</th><th>YTD %</th>
    <th>RSI 14</th><th>Sector</th><th>Avg Vol</th>
    <th>vs EMA20</th><th>EMA50</th><th>EMA200</th>
  </tr>
  {stock_rows}
</table>
</body>
</html>
"""


def save_html_report(sector_ranking, leading_sectors, results, cfg, watchlist_filename=""):
    sector_rows_html = ""
    for sector, gain in sector_ranking:
        is_lead = sector in leading_sectors
        star = '<span class="star">★</span> ' if is_lead else ""
        cls  = 'class="sector-lead"' if is_lead else ""
        badge = '<span class="badge">Leading</span>' if is_lead else ""
        g_cls = "up" if gain > 0 else ""
        sector_rows_html += (
            f'<tr><td {cls}>{star}{sector}</td>'
            f'<td class="{g_cls}">{gain:+.1f}%</td>'
            f'<td>{badge}</td></tr>\n'
        )

    stock_rows_html = ""
    for i, s in enumerate(results, 1):
        ema20    = s.get("ema20")
        vs_ema   = (f"{(s['price'] - ema20) / ema20 * 100:+.1f}%" if ema20 else "─")
        rsi_str  = f"{s['rsi14']:.0f}" if s["rsi14"] else "─"
        ema50_str  = f"{s['ema50']:.2f}"  if s["ema50"]  else "─"
        ema200_str = f"{s['ema200']:.2f}" if s["ema200"] else "─"
        stock_rows_html += (
            f'<tr>'
            f'<td>{i}</td>'
            f'<td class="ticker">{s["ticker"]}</td>'
            f'<td>${s["price"]:.2f}</td>'
            f'<td class="up">{s["ytd_pct"]:+.1f}%</td>'
            f'<td>{rsi_str}</td>'
            f'<td>{s["sector"]}</td>'
            f'<td>{fmt_volume(s["avg_vol"])}</td>'
            f'<td>{vs_ema}</td>'
            f'<td>{ema50_str}</td>'
            f'<td>{ema200_str}</td>'
            f'</tr>\n'
        )

    today = date.today().isoformat()
    html  = HTML_TEMPLATE.format(
        date=today,
        datetime=datetime.now().strftime("%Y-%m-%d %H:%M"),
        count=len(results),
        ytd_min=cfg["ytd_min_pct"],
        top_n=cfg["top_sector_count"],
        sector_rows=sector_rows_html,
        stock_rows=stock_rows_html or "<tr><td colspan='10'>No stocks passed filters today.</td></tr>",
        watchlist_filename=watchlist_filename,
    )

    out_dir  = Path(__file__).parent.parent / "data"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"screener_{today}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


def save_tradingview_watchlist(results: list, cfg: dict) -> "Path":
    """
    Export screened stocks as a TradingView-importable watchlist.
    Format: ###Sector headers + one ticker per line.
    Import in TV: Watchlist panel → ⋮ → Import watchlist → select this file.
    """
    today    = date.today().isoformat()
    out_dir  = Path(__file__).parent.parent / "data"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"screener_{today}_watchlist.txt"

    lines = [
        f"### US Stock Screener {today}",
        f"### Criteria: Bullish EMA (5>10>20>50>200) | YTD >{cfg['ytd_min_pct']:.0f}% | Top-{cfg['top_sector_count']} sectors",
        "",
    ]

    # Group by sector, keep original YTD-descending order within each group
    sectors_seen: list[str] = []
    by_sector: dict[str, list] = {}
    for s in results:
        sec = s["sector"]
        if sec not in by_sector:
            by_sector[sec] = []
            sectors_seen.append(sec)
        by_sector[sec].append(s)

    for sec in sectors_seen:
        lines.append(f"###{sec}")
        for s in by_sector[sec]:
            ytd  = s["ytd_pct"]
            rsi  = f"RSI {s['rsi14']:.0f}" if s["rsi14"] else ""
            note = f"  # YTD {ytd:+.1f}%  {rsi}".rstrip()
            lines.append(s["ticker"] + note)
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def save_json_report(sector_ranking, leading_sectors, results, cfg):
    today = date.today().isoformat()
    out_dir = Path(__file__).parent.parent / "data"
    out_dir.mkdir(exist_ok=True)
    payload = {
        "date": today,
        "criteria": {
            "ytd_min_pct": cfg["ytd_min_pct"],
            "top_sector_count": cfg["top_sector_count"],
            "ema_alignment": "5>10>20>50>200",
        },
        "sector_ranking": [{"sector": s, "ytd_pct": round(g, 2)} for s, g in sector_ranking],
        "leading_sectors": leading_sectors,
        "results": results,
    }
    out_path = out_dir / f"screener_{today}.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return out_path


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="US Stock Daily Screener")
    p.add_argument("--ytd",     type=float, default=DEFAULTS["ytd_min_pct"],
                   help=f"Minimum YTD %% gain (default {DEFAULTS['ytd_min_pct']})")
    p.add_argument("--sectors", type=int,   default=DEFAULTS["top_sector_count"],
                   help=f"Number of leading sectors (default {DEFAULTS['top_sector_count']})")
    p.add_argument("--html",    action="store_true",
                   help="Also save an HTML report (open in browser)")
    p.add_argument("--min-vol", type=int,   default=DEFAULTS["min_avg_volume"],
                   help="Min avg daily volume (default 500000)")
    return p.parse_args()


def main():
    args = parse_args()
    cfg  = {**DEFAULTS,
            "ytd_min_pct":     args.ytd,
            "top_sector_count": args.sectors,
            "min_avg_volume":  args.min_vol}

    print(bold("\n  US Stock Screener"))
    print(f"  YTD >{cfg['ytd_min_pct']:.0f}%  |  Top-{cfg['top_sector_count']} sectors"
          f"  |  Bullish EMA alignment\n")

    # Step 1 – rank sectors
    print(bold("  [1/3] Ranking sectors"))
    sector_ranking = rank_sectors(cfg)
    if not sector_ranking:
        print("  ERROR: Could not retrieve sector data. Check internet connection.")
        sys.exit(1)
    leading_sectors = [s for s, _ in sector_ranking[: cfg["top_sector_count"]]]

    # Step 2 – screen stocks
    print(bold(f"\n  [2/3] Screening stocks  (leading: {', '.join(leading_sectors)})"))
    results = screen_stocks(leading_sectors, cfg)

    # Step 3 – output
    print(bold(f"\n  [3/3] Generating report  ({len(results)} passed)\n"))
    print_terminal_report(sector_ranking, leading_sectors, results, cfg)

    json_path = save_json_report(sector_ranking, leading_sectors, results, cfg)
    print(f"  JSON       → {json_path}")

    tv_path = save_tradingview_watchlist(results, cfg)
    print(f"  TV watchlist → {tv_path}")

    if args.html:
        html_path = save_html_report(
            sector_ranking, leading_sectors, results, cfg,
            watchlist_filename=tv_path.name,
        )
        print(f"  HTML       → {html_path}")

    print()


if __name__ == "__main__":
    main()
