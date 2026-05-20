"""
Generate realistic synthetic NAS100 5-minute OHLCV data for 5 years.
Uses real NAS100 statistical properties:
  - Annualized vol ~20%, daily vol ~1.25%
  - Intraday patterns (open/close higher vol, midday calmer)
  - Trending + mean-reversion regime switching
  - Gap opens, news shocks, volume profiles
"""
import json, os, math, random
from datetime import datetime, date, timedelta

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "data", "nas100_5min.json")

SEED = 42
random.seed(SEED)

# NAS100 parameters (based on 2019-2024 data)
START_PRICE = 7500.0        # NAS100 level circa Jan 2019
ANNUAL_DRIFT = 0.13         # ~13% annual drift
ANNUAL_VOL = 0.20           # ~20% annual vol
TRADING_DAYS_PER_YEAR = 252
BARS_PER_DAY = 78           # 09:30–16:00 = 6.5 hrs × 12 bars/hr
DT = 1 / (TRADING_DAYS_PER_YEAR * BARS_PER_DAY)

def market_days(start: date, end: date):
    """Yield trading days (Mon-Fri, excluding major US holidays)."""
    HOLIDAYS = {
        # 2019
        date(2019, 1, 1), date(2019, 1, 21), date(2019, 2, 18),
        date(2019, 4, 19), date(2019, 5, 27), date(2019, 7, 4),
        date(2019, 9, 2), date(2019, 11, 28), date(2019, 12, 25),
        # 2020
        date(2020, 1, 1), date(2020, 1, 20), date(2020, 2, 17),
        date(2020, 4, 10), date(2020, 5, 25), date(2020, 7, 3),
        date(2020, 9, 7), date(2020, 11, 26), date(2020, 12, 25),
        # 2021
        date(2021, 1, 1), date(2021, 1, 18), date(2021, 2, 15),
        date(2021, 4, 2), date(2021, 5, 31), date(2021, 7, 5),
        date(2021, 9, 6), date(2021, 11, 25), date(2021, 12, 24),
        # 2022
        date(2022, 1, 17), date(2022, 2, 21), date(2022, 4, 15),
        date(2022, 5, 30), date(2022, 6, 20), date(2022, 7, 4),
        date(2022, 9, 5), date(2022, 11, 24), date(2022, 12, 26),
        # 2023
        date(2023, 1, 2), date(2023, 1, 16), date(2023, 2, 20),
        date(2023, 4, 7), date(2023, 5, 29), date(2023, 7, 4),
        date(2023, 9, 4), date(2023, 11, 23), date(2023, 12, 25),
        # 2024
        date(2024, 1, 1), date(2024, 1, 15), date(2024, 2, 19),
        date(2024, 3, 29), date(2024, 5, 27), date(2024, 7, 4),
        date(2024, 9, 2), date(2024, 11, 28), date(2024, 12, 25),
    }
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in HOLIDAYS:
            yield d
        d += timedelta(days=1)

def intraday_vol_multiplier(bar_idx: int) -> float:
    """U-shaped vol: higher at open/close, lower midday."""
    x = bar_idx / BARS_PER_DAY
    return 1.0 + 1.2 * math.exp(-20 * x) + 0.6 * math.exp(-20 * (1 - x))

def intraday_volume_multiplier(bar_idx: int) -> float:
    """Volume highest at open, spikes at close."""
    x = bar_idx / BARS_PER_DAY
    return 2.5 * math.exp(-15 * x) + 0.5 + 1.8 * math.exp(-20 * (1 - x))

def generate_candle(prev_close: float, bar_idx: int, trend_factor: float) -> dict:
    """Generate one OHLCV candle."""
    vol_mult = intraday_vol_multiplier(bar_idx)
    bar_vol = ANNUAL_VOL * math.sqrt(DT) * vol_mult
    drift = ANNUAL_DRIFT * DT * trend_factor

    ret = drift + bar_vol * _randn()
    close = prev_close * math.exp(ret)

    # OHLC spread: proportional to bar volatility
    spread = abs(prev_close * bar_vol * (0.3 + 0.7 * random.random()))
    direction = 1 if close >= prev_close else -1

    high = max(prev_close, close) + spread * random.uniform(0.1, 0.8)
    low = min(prev_close, close) - spread * random.uniform(0.1, 0.8)
    open_price = prev_close + direction * spread * random.uniform(0, 0.4)
    open_price = max(low, min(high, open_price))

    base_volume = int(prev_close * 80 * intraday_volume_multiplier(bar_idx))
    volume = max(1, int(base_volume * (0.6 + 0.8 * random.random())))

    return {
        "o": round(open_price, 2),
        "h": round(high, 2),
        "l": round(low, 2),
        "c": round(close, 2),
        "v": volume,
    }

def _randn() -> float:
    """Box-Muller normal."""
    u, v = random.random(), random.random()
    return math.sqrt(-2 * math.log(max(u, 1e-10))) * math.cos(2 * math.pi * v)

def generate_all() -> list[dict]:
    start_date = date(2019, 1, 2)
    end_date = date(2024, 1, 1)

    records = []
    price = START_PRICE

    # Regime state
    trend_factor = 1.0
    regime_days = 0
    shock_countdown = 0

    days = list(market_days(start_date, end_date))
    total_days = len(days)
    print(f"Generating {total_days} trading days × {BARS_PER_DAY} bars …")

    for day_idx, day in enumerate(days):
        # Switch regime every ~20-60 days
        regime_days -= 1
        if regime_days <= 0:
            trend_factor = random.choice([1.5, 1.0, 1.0, 0.5, -0.5])
            regime_days = random.randint(20, 60)

        # Occasional shock (earnings season, macro events)
        if shock_countdown == 0 and random.random() < 0.003:
            shock_mult = random.choice([0.97, 0.98, 1.02, 1.03])
            price *= shock_mult
            shock_countdown = 3
        elif shock_countdown > 0:
            shock_countdown -= 1

        # Gap open (overnight move)
        gap_ret = (ANNUAL_DRIFT / TRADING_DAYS_PER_YEAR +
                   ANNUAL_VOL * math.sqrt(1 / TRADING_DAYS_PER_YEAR) * _randn() * 0.4)
        price *= math.exp(gap_ret)

        day_open = price

        for bar_idx in range(BARS_PER_DAY):
            hours = 9 * 60 + 30 + bar_idx * 5
            hh = hours // 60
            mm = hours % 60
            ts = f"{day.isoformat()} {hh:02d}:{mm:02d}"

            candle = generate_candle(price, bar_idx, trend_factor)
            candle["t"] = ts
            records.append(candle)
            price = candle["c"]

        if day_idx % 100 == 0:
            print(f"  {day} — price={price:.0f} ({day_idx}/{total_days})")

    print(f"Total candles: {len(records)}")
    return records

def build_flashcards(records: list[dict]) -> list[dict]:
    """
    60 candles context (5 hours), predict next 6 bars (30 min).
    Signal based on net return exceeding ±0.25%.
    """
    cards = []
    window = 60
    future = 6
    threshold = 0.0025

    # Sample every 3rd bar to get ~diverse cards without redundancy
    indices = range(window, len(records) - future, 3)

    for i in indices:
        context = records[i - window: i]
        ahead = records[i: i + future]

        entry_price = records[i]["o"]
        close_price = ahead[-1]["c"]
        max_price = max(c["h"] for c in ahead)
        min_price = min(c["l"] for c in ahead)

        net_move = (close_price - entry_price) / entry_price
        up_move = (max_price - entry_price) / entry_price
        down_move = (entry_price - min_price) / entry_price

        if net_move > threshold:
            signal = "BUY"
        elif net_move < -threshold:
            signal = "SELL"
        else:
            signal = "HOLD"

        cards.append({
            "id": len(cards),
            "date": records[i]["t"][:10],
            "time": records[i]["t"][11:],
            "context": context,
            "entry": round(entry_price, 2),
            "future": ahead,
            "signal": signal,
            "net_pct": round(net_move * 100, 3),
            "up_pct": round(up_move * 100, 3),
            "down_pct": round(down_move * 100, 3),
        })

    return cards

def main():
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    records = generate_all()
    cards = build_flashcards(records)

    # Stats
    signals = [c["signal"] for c in cards]
    buys = signals.count("BUY")
    sells = signals.count("SELL")
    holds = signals.count("HOLD")
    print(f"Cards: {len(cards)} | BUY:{buys} SELL:{sells} HOLD:{holds}")

    output = {
        "generated": datetime.now().isoformat(),
        "ticker": "NAS100 (synthetic)",
        "period": "2019-01-02 to 2024-01-01",
        "note": "Synthetic data generated with realistic NAS100 statistical properties",
        "total_candles": len(records),
        "total_cards": len(cards),
        "cards": cards,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, separators=(",", ":"))

    size_mb = os.path.getsize(OUTPUT_FILE) / 1024 / 1024
    print(f"Saved → {OUTPUT_FILE} ({size_mb:.1f} MB)")

if __name__ == "__main__":
    main()
