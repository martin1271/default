#!/usr/bin/env python3
"""每日美股篩選器

篩選條件:
1. 板塊強度:以 11 檔 SPDR 板塊 ETF 的 YTD 報酬排名,取前 N 名板塊
2. 個股範圍:S&P 500 + Nasdaq-100 成分股中屬於強勢板塊者
3. EMA 多頭排列:收盤價 > EMA20 > EMA50 > EMA200
4. YTD 報酬 >= +50%
5. 期權異動(巨鯨單):單一合約成交量 >= MIN_VOLUME、
   成交量/未平倉量 (Vol/OI) >= MIN_VOL_OI_RATIO(代表是新開倉的大單,
   而非平倉)、名目金額 (成交量 x 權利金 x 100) >= MIN_NOTIONAL

輸出:reports/YYYY-MM-DD.md、reports/latest.md、reports/YYYY-MM-DD_options.csv
"""

import datetime as dt
import os
import sys
import time
import traceback
from io import StringIO

import numpy as np
import pandas as pd
import requests
import yfinance as yf

# ---------------------------------------------------------------- 參數設定
CONFIG = {
    "TOP_N_SECTORS": 3,          # 取 YTD 表現前幾名的板塊
    "YTD_THRESHOLD": 0.50,       # 個股 YTD 報酬門檻 (+50%)
    "EMA_PERIODS": (20, 50, 200),
    "MAX_OPTION_TICKERS": 40,    # 最多掃描幾檔個股的期權鏈 (控制 API 用量)
    "MAX_EXPIRIES": 5,           # 每檔股票最多掃描幾個到期日
    "EXPIRY_WINDOW_DAYS": 60,    # 只看 60 天內到期的合約
    "MIN_VOLUME": 500,           # 異動單最低成交量 (張)
    "MIN_VOL_OI_RATIO": 2.0,     # 成交量 / 未平倉量 下限
    "MIN_NOTIONAL": 1_000_000,   # 名目金額下限 (美元)
    "TOP_FLAGS_PER_TICKER": 10,  # 每檔股票最多列出幾筆異動單
}

# GICS 板塊 -> SPDR 板塊 ETF
SECTOR_ETFS = {
    "Information Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Communication Services": "XLC",
    "Industrials": "XLI",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
}

SECTOR_ZH = {
    "Information Technology": "資訊科技",
    "Health Care": "醫療保健",
    "Financials": "金融",
    "Consumer Discretionary": "非必需消費",
    "Communication Services": "通訊服務",
    "Industrials": "工業",
    "Consumer Staples": "必需消費",
    "Energy": "能源",
    "Utilities": "公用事業",
    "Real Estate": "房地產",
    "Materials": "原物料",
}

WIKI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


# ---------------------------------------------------------------- 工具函式
def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def fetch_wiki_tables(url):
    resp = requests.get(url, headers=WIKI_HEADERS, timeout=30)
    resp.raise_for_status()
    return pd.read_html(StringIO(resp.text))


def get_universe():
    """抓取 S&P 500 + Nasdaq-100 成分股 (代碼 / 名稱 / GICS 板塊)。"""
    rows = []

    # S&P 500
    try:
        tables = fetch_wiki_tables(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        sp500 = tables[0]
        for _, r in sp500.iterrows():
            rows.append({
                "ticker": str(r["Symbol"]).strip(),
                "name": str(r["Security"]).strip(),
                "sector": str(r["GICS Sector"]).strip(),
            })
        log(f"S&P 500 成分股: {len(sp500)} 檔")
    except Exception as e:
        log(f"警告: 抓取 S&P 500 成分股失敗: {e}")

    # Nasdaq-100
    try:
        tables = fetch_wiki_tables("https://en.wikipedia.org/wiki/Nasdaq-100")
        nd100 = None
        for t in tables:
            cols = [str(c) for c in t.columns]
            if any("Ticker" in c or "Symbol" in c for c in cols) \
                    and any("GICS Sector" in c for c in cols):
                nd100 = t
                break
        if nd100 is not None:
            tick_col = next(c for c in nd100.columns
                            if "Ticker" in str(c) or "Symbol" in str(c))
            name_col = next(c for c in nd100.columns if "Company" in str(c))
            sect_col = next(c for c in nd100.columns
                            if str(c) == "GICS Sector"
                            or ("GICS Sector" in str(c)
                                and "Sub" not in str(c)))
            for _, r in nd100.iterrows():
                rows.append({
                    "ticker": str(r[tick_col]).strip(),
                    "name": str(r[name_col]).strip(),
                    "sector": str(r[sect_col]).strip(),
                })
            log(f"Nasdaq-100 成分股: {len(nd100)} 檔")
    except Exception as e:
        log(f"警告: 抓取 Nasdaq-100 成分股失敗: {e}")

    if not rows:
        raise RuntimeError("無法取得任何成分股名單")

    df = pd.DataFrame(rows).drop_duplicates(subset="ticker")
    # yfinance 用 '-' 取代 '.' (例如 BRK.B -> BRK-B)
    df["yf_ticker"] = df["ticker"].str.replace(".", "-", regex=False)
    return df


def ytd_return(close: pd.Series):
    """以今年第一個交易日收盤價為基準計算 YTD 報酬。"""
    close = close.dropna()
    if close.empty:
        return None
    year = pd.Timestamp.now().year
    this_year = close[close.index >= pd.Timestamp(year=year, month=1, day=1)]
    if len(this_year) < 2:
        return None
    return float(this_year.iloc[-1] / this_year.iloc[0] - 1.0)


def get_top_sectors(n):
    """下載板塊 ETF 並依 YTD 報酬排序,回傳 (排名 DataFrame, 前 n 名板塊)。"""
    etfs = list(SECTOR_ETFS.values())
    data = yf.download(etfs, period="2y", interval="1d",
                       auto_adjust=True, group_by="ticker",
                       threads=True, progress=False)
    recs = []
    for sector, etf in SECTOR_ETFS.items():
        try:
            close = data[etf]["Close"]
        except Exception:
            continue
        r = ytd_return(close)
        if r is not None:
            recs.append({"sector": sector, "etf": etf, "ytd": r})
    rank = pd.DataFrame(recs).sort_values("ytd", ascending=False) \
                             .reset_index(drop=True)
    top = rank.head(n)["sector"].tolist()
    return rank, top


def screen_stocks(universe: pd.DataFrame, cfg):
    """批次下載日線,檢查 EMA 多頭排列 + YTD 門檻。"""
    tickers = universe["yf_ticker"].tolist()
    log(f"批次下載 {len(tickers)} 檔個股日線資料...")
    data = yf.download(tickers, period="2y", interval="1d",
                       auto_adjust=True, group_by="ticker",
                       threads=True, progress=False)
    passed = []
    for _, row in universe.iterrows():
        yft = row["yf_ticker"]
        try:
            close = data[yft]["Close"].dropna()
        except Exception:
            continue
        if len(close) < max(cfg["EMA_PERIODS"]) + 20:
            continue
        r = ytd_return(close)
        if r is None or r < cfg["YTD_THRESHOLD"]:
            continue
        emas = {p: close.ewm(span=p, adjust=False).mean().iloc[-1]
                for p in cfg["EMA_PERIODS"]}
        price = float(close.iloc[-1])
        chain = [price] + [emas[p] for p in sorted(cfg["EMA_PERIODS"])]
        # 多頭排列: 價格 > 短期 EMA > 中期 EMA > 長期 EMA
        if all(a > b for a, b in zip(chain, chain[1:])):
            passed.append({
                "ticker": row["ticker"], "yf_ticker": yft,
                "name": row["name"], "sector": row["sector"],
                "price": price, "ytd": r,
                **{f"ema{p}": float(emas[p]) for p in cfg["EMA_PERIODS"]},
            })
    df = pd.DataFrame(passed)
    if not df.empty:
        df = df.sort_values("ytd", ascending=False).reset_index(drop=True)
    return df


def find_unusual_options(yf_ticker, cfg):
    """掃描期權鏈,找出疑似巨鯨異動單。

    判斷標準 (單腿合約層級):
      - 成交量 >= MIN_VOLUME
      - 成交量 / 未平倉量 >= MIN_VOL_OI_RATIO (遠超平時、疑似新開倉大單)
      - 名目金額 = 成交量 x 權利金 x 100 >= MIN_NOTIONAL
    """
    flags = []
    today = dt.date.today()
    try:
        tk = yf.Ticker(yf_ticker)
        expiries = tk.options or []
    except Exception:
        return flags

    usable = []
    for e in expiries:
        try:
            d = dt.datetime.strptime(e, "%Y-%m-%d").date()
        except ValueError:
            continue
        if 0 <= (d - today).days <= cfg["EXPIRY_WINDOW_DAYS"]:
            usable.append(e)
    usable = usable[:cfg["MAX_EXPIRIES"]]

    for exp in usable:
        try:
            chain = tk.option_chain(exp)
        except Exception:
            continue
        for side, df in (("CALL", chain.calls), ("PUT", chain.puts)):
            if df is None or df.empty:
                continue
            df = df.copy()
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce") \
                             .fillna(0)
            df["openInterest"] = pd.to_numeric(df["openInterest"],
                                               errors="coerce").fillna(0)
            df["lastPrice"] = pd.to_numeric(df["lastPrice"],
                                            errors="coerce").fillna(0)
            df["notional"] = df["volume"] * df["lastPrice"] * 100
            df["vol_oi"] = df["volume"] / df["openInterest"].replace(0, np.nan)
            df["vol_oi"] = df["vol_oi"].fillna(np.inf)

            hit = df[(df["volume"] >= cfg["MIN_VOLUME"])
                     & (df["vol_oi"] >= cfg["MIN_VOL_OI_RATIO"])
                     & (df["notional"] >= cfg["MIN_NOTIONAL"])]
            for _, r in hit.iterrows():
                iv = r.get("impliedVolatility")
                flags.append({
                    "ticker": yf_ticker,
                    "type": side,
                    "expiry": exp,
                    "strike": float(r["strike"]),
                    "lastPrice": float(r["lastPrice"]),
                    "volume": int(r["volume"]),
                    "openInterest": int(r["openInterest"]),
                    "vol_oi": float(r["vol_oi"]) if np.isfinite(r["vol_oi"])
                              else None,
                    "notional": float(r["notional"]),
                    "iv": float(iv) if iv is not None and pd.notna(iv)
                          else None,
                })
        time.sleep(0.3)

    flags.sort(key=lambda x: x["notional"], reverse=True)
    return flags[:cfg["TOP_FLAGS_PER_TICKER"]]


# ---------------------------------------------------------------- 報告輸出
def fmt_money(v):
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.2f}M"
    return f"${v/1e3:.0f}K"


def build_report(date_str, sector_rank, top_sectors, result, options_map, cfg):
    lines = []
    lines.append(f"# 每日美股篩選報告 — {date_str}")
    lines.append("")
    lines.append("篩選條件:強勢板塊 (板塊 ETF YTD 前 "
                 f"{cfg['TOP_N_SECTORS']} 名) ・ EMA 多頭排列 "
                 f"(價格 > EMA{' > EMA'.join(map(str, sorted(cfg['EMA_PERIODS'])))})"
                 f" ・ YTD ≥ +{cfg['YTD_THRESHOLD']*100:.0f}%"
                 " ・ 期權巨鯨異動單")
    lines.append("")

    # 板塊排名
    lines.append("## 一、板塊 YTD 排名")
    lines.append("")
    lines.append("| 排名 | 板塊 | ETF | YTD | 入選 |")
    lines.append("|---|---|---|---|---|")
    for i, r in sector_rank.iterrows():
        star = "✅" if r["sector"] in top_sectors else ""
        zh = SECTOR_ZH.get(r["sector"], r["sector"])
        lines.append(f"| {i+1} | {zh} ({r['sector']}) | {r['etf']} "
                     f"| {r['ytd']*100:+.1f}% | {star} |")
    lines.append("")

    # 個股篩選結果
    lines.append("## 二、通過篩選的個股")
    lines.append("")
    if result.empty:
        lines.append("今日沒有個股同時滿足所有條件。")
        lines.append("")
    else:
        ema_cols = "".join(f"| EMA{p} " for p in sorted(cfg["EMA_PERIODS"]))
        lines.append(f"| 代碼 | 名稱 | 板塊 | 收盤價 | YTD {ema_cols}| 異動單 |")
        lines.append("|---|---|---|---|---|" +
                     "---|" * len(cfg["EMA_PERIODS"]) + "---|")
        for _, r in result.iterrows():
            n_flags = len(options_map.get(r["yf_ticker"], []))
            flag_txt = f"🐳 {n_flags} 筆" if n_flags else "—"
            emas = "".join(f"| {r[f'ema{p}']:.2f} "
                           for p in sorted(cfg["EMA_PERIODS"]))
            zh = SECTOR_ZH.get(r["sector"], r["sector"])
            lines.append(f"| **{r['ticker']}** | {r['name']} | {zh} "
                         f"| {r['price']:.2f} | {r['ytd']*100:+.1f}% "
                         f"{emas}| {flag_txt} |")
        lines.append("")

    # 期權異動明細
    lines.append("## 三、期權巨鯨異動明細")
    lines.append("")
    lines.append(f"> 異動定義:單一合約成交量 ≥ {cfg['MIN_VOLUME']} 張、"
                 f"Vol/OI ≥ {cfg['MIN_VOL_OI_RATIO']:.0f}"
                 "(成交量遠超未平倉量 → 疑似新開倉巨鯨單)、"
                 f"名目金額 ≥ {fmt_money(cfg['MIN_NOTIONAL'])}。"
                 "資料來源為日終彙總,僅為單腿合約層級的代理指標,"
                 "無法 100% 排除多腿組合單。")
    lines.append("")
    any_flag = False
    for _, r in (result.iterrows() if not result.empty else []):
        flags = options_map.get(r["yf_ticker"], [])
        if not flags:
            continue
        any_flag = True
        lines.append(f"### {r['ticker']} — {r['name']}")
        lines.append("")
        lines.append("| 類型 | 到期日 | 行權價 | 權利金 | 成交量 | OI "
                     "| Vol/OI | 名目金額 | IV |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for f in flags:
            voi = f"{f['vol_oi']:.1f}" if f["vol_oi"] is not None else "∞"
            iv = f"{f['iv']*100:.0f}%" if f["iv"] else "—"
            emoji = "🟢" if f["type"] == "CALL" else "🔴"
            lines.append(f"| {emoji} {f['type']} | {f['expiry']} "
                         f"| {f['strike']:.1f} | {f['lastPrice']:.2f} "
                         f"| {f['volume']:,} | {f['openInterest']:,} "
                         f"| {voi} | {fmt_money(f['notional'])} | {iv} |")
        lines.append("")
    if not any_flag:
        lines.append("通過篩選的個股今日沒有偵測到符合門檻的期權異動單。")
        lines.append("")

    lines.append("---")
    lines.append("*本報告由自動化腳本產生,資料來源 Yahoo Finance,"
                 "僅供研究參考,不構成投資建議。*")
    lines.append("")
    return "\n".join(lines)


def main():
    cfg = CONFIG
    date_str = dt.date.today().isoformat()
    os.makedirs("reports", exist_ok=True)

    log("步驟 1/4: 計算板塊 YTD 排名...")
    sector_rank, top_sectors = get_top_sectors(cfg["TOP_N_SECTORS"])
    log(f"強勢板塊: {top_sectors}")

    log("步驟 2/4: 抓取成分股名單...")
    universe = get_universe()
    universe = universe[universe["sector"].isin(top_sectors)] \
        .reset_index(drop=True)
    log(f"強勢板塊內個股: {len(universe)} 檔")

    log("步驟 3/4: 篩選 EMA 多頭排列 + YTD...")
    result = screen_stocks(universe, cfg)
    log(f"通過技術面篩選: {len(result)} 檔")

    log("步驟 4/4: 掃描期權異動...")
    options_map = {}
    all_flags = []
    scan_list = result["yf_ticker"].tolist()[:cfg["MAX_OPTION_TICKERS"]] \
        if not result.empty else []
    for i, yft in enumerate(scan_list, 1):
        log(f"  ({i}/{len(scan_list)}) {yft}")
        try:
            flags = find_unusual_options(yft, cfg)
        except Exception:
            traceback.print_exc()
            flags = []
        options_map[yft] = flags
        all_flags.extend(flags)
        time.sleep(0.5)

    report = build_report(date_str, sector_rank, top_sectors,
                          result, options_map, cfg)
    path = f"reports/{date_str}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    with open("reports/latest.md", "w", encoding="utf-8") as f:
        f.write(report)
    if all_flags:
        pd.DataFrame(all_flags).to_csv(f"reports/{date_str}_options.csv",
                                       index=False)
    log(f"報告已輸出: {path}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
