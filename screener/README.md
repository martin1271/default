# 每日美股篩選器(EMA 多頭排列 + YTD+50% + 強勢板塊 + 期權巨鯨異動)

每個交易日自動產生一份篩選報告,輸出到 `reports/` 目錄:

- `reports/latest.md` — 永遠是最新一份報告(每天直接看這份即可)
- `reports/YYYY-MM-DD.md` — 每日存檔
- `reports/YYYY-MM-DD_options.csv` — 當日所有異動單原始資料(方便自行分析)

## 篩選邏輯

| 步驟 | 條件 | 說明 |
|---|---|---|
| 1. 強勢板塊 | 11 檔 SPDR 板塊 ETF 依 YTD 報酬排名,取前 3 名 | XLK/XLV/XLF/XLY/XLC/XLI/XLP/XLE/XLU/XLRE/XLB |
| 2. 個股範圍 | S&P 500 + Nasdaq-100 中屬於強勢板塊的個股 | 確保流動性與期權市場深度 |
| 3. EMA 多頭排列 | 收盤價 > EMA20 > EMA50 > EMA200 | 日線級別 |
| 4. 動能 | YTD 報酬 ≥ +50% | 以今年第一個交易日收盤價為基準 |
| 5. 期權巨鯨異動 | 見下方定義 | 只掃描通過前四關的個股 |

### 期權異動(巨鯨單)的判定

對 60 天內到期的所有單一合約(call / put 分開看),同時滿足:

1. **成交量 ≥ 500 張** — 排除小單
2. **Vol/OI ≥ 2** — 當日成交量是未平倉量的 2 倍以上,代表「遠超平時交易量」,
   大概率是新開倉的大單而非平倉
3. **名目金額 ≥ $1M** — 成交量 × 權利金 × 100,確保是巨鯨級別的資金

> ⚠️ 限制:免費資料源(Yahoo Finance)只有日終彙總的合約成交量,沒有逐筆
> 成交(time & sales),因此無法 100% 區分「一張巨鯨單」與「多筆散單累積」,
> 也無法完全排除多腿組合單(spread)。以上是業界常用的代理指標,若需要逐筆
> 大單掃描(sweep/block 偵測),需接 CBOE / OPRA 付費數據或 Unusual Whales、
> BarChart 之類的付費 API。

## 自動化排程

`.github/workflows/daily-screener.yml` 由 GitHub Actions 在
**每週一至五 21:30 UTC**(美東收盤後)自動執行,並把報告 commit 回 repo。

> 注意:GitHub 的 `schedule` 排程只會在 **repo 預設分支** 上的 workflow 生效,
> 此檔案需要合併到預設分支後排程才會啟動。

也可以隨時手動觸發:GitHub → Actions → "Daily Stock Screener" → Run workflow。

## 本機執行

```bash
pip install -r screener/requirements.txt
python screener/daily_screener.py
```

## 調整參數

所有門檻都集中在 `daily_screener.py` 開頭的 `CONFIG`:

```python
CONFIG = {
    "TOP_N_SECTORS": 3,        # 取前幾名板塊
    "YTD_THRESHOLD": 0.50,     # YTD 門檻
    "EMA_PERIODS": (20, 50, 200),
    "MIN_VOLUME": 500,         # 異動單最低成交量
    "MIN_VOL_OI_RATIO": 2.0,   # Vol/OI 下限
    "MIN_NOTIONAL": 1_000_000, # 名目金額下限
    ...
}
```
