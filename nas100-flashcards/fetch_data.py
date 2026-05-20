"""
NAS100 5-minute data fetcher.
yfinance supports up to 60 days of 5-min data per request.
This script fetches in chunks and saves to JSON for the flashcard app.
"""
import yfinance as yf
import pandas as pd
import json
import os
from datetime import datetime, timedelta
import time

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "data", "nas100_5min.json")
TICKER = "NQ=F"   # NAS100 futures; fallback: "^NDX"
CHUNK_DAYS = 58   # yfinance 5-min limit per request

def fetch_chunk(start: datetime, end: datetime) -> pd.DataFrame:
    ticker = yf.Ticker(TICKER)
    df = ticker.history(start=start.strftime("%Y-%m-%d"),
                        end=end.strftime("%Y-%m-%d"),
                        interval="5m",
                        auto_adjust=True)
    if df.empty:
        ticker2 = yf.Ticker("^NDX")
        df = ticker2.history(start=start.strftime("%Y-%m-%d"),
                             end=end.strftime("%Y-%m-%d"),
                             interval="5m",
                             auto_adjust=True)
    return df

def fetch_all() -> list[dict]:
    """Fetch available 5-min data (up to 60 days back from today)."""
    end = datetime.now()
    start = end - timedelta(days=CHUNK_DAYS)

    print(f"Fetching {TICKER} 5-min data: {start.date()} → {end.date()}")
    df = fetch_chunk(start, end)

    if df.empty:
        print("No data returned. Check ticker or network.")
        return []

    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")

    # Keep only regular market hours: 09:30–16:00 ET
    df = df.between_time("09:30", "16:00")
    df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])

    records = []
    for ts, row in df.iterrows():
        records.append({
            "t": ts.strftime("%Y-%m-%d %H:%M"),
            "o": round(float(row["Open"]), 2),
            "h": round(float(row["High"]), 2),
            "l": round(float(row["Low"]), 2),
            "c": round(float(row["Close"]), 2),
            "v": int(row["Volume"]),
        })

    print(f"Fetched {len(records)} candles")
    return records

def build_flashcards(records: list[dict]) -> list[dict]:
    """
    Each flashcard shows the last 60 candles (5 hours of context),
    then tests the user on what happens in the NEXT 6 candles (30 min).
    Answer: BUY / SELL / HOLD based on whether price goes up/down >0.3%.
    """
    cards = []
    window = 60
    future = 6
    threshold = 0.003  # 0.3%

    for i in range(window, len(records) - future):
        context = records[i - window: i]
        ahead = records[i: i + future]

        entry_price = records[i]["o"]
        max_price = max(c["h"] for c in ahead)
        min_price = min(c["l"] for c in ahead)
        close_price = ahead[-1]["c"]

        up_move = (max_price - entry_price) / entry_price
        down_move = (entry_price - min_price) / entry_price
        net_move = (close_price - entry_price) / entry_price

        if net_move > threshold:
            signal = "BUY"
        elif net_move < -threshold:
            signal = "SELL"
        else:
            signal = "HOLD"

        cards.append({
            "id": i,
            "date": records[i]["t"][:10],
            "time": records[i]["t"][11:],
            "context": context,
            "entry": entry_price,
            "future": ahead,
            "signal": signal,
            "net_pct": round(net_move * 100, 3),
            "up_pct": round(up_move * 100, 3),
            "down_pct": round(down_move * 100, 3),
        })

    return cards

def main():
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    records = fetch_all()
    if not records:
        return

    cards = build_flashcards(records)
    print(f"Generated {len(cards)} flashcards")

    output = {
        "generated": datetime.now().isoformat(),
        "ticker": TICKER,
        "total_candles": len(records),
        "total_cards": len(cards),
        "cards": cards,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, separators=(",", ":"))

    print(f"Saved → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
