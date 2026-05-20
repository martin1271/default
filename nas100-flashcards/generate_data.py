"""
Generate 5 years of realistic synthetic NAS100 5-minute OHLCV data.
Uses GBM with intraday volatility patterns calibrated to NAS100 historical stats.
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, time
import pickle, os

np.random.seed(42)

# ── Parameters calibrated to NAS100 2019-2024 ────────────────────────────────
START_PRICE   = 7800.0          # NAS100 approx end-2018
ANNUAL_RETURN = 0.18            # ~18% annualised
ANNUAL_VOL    = 0.22            # ~22% annualised
JUMP_PROB     = 0.004           # prob of gap/news jump per bar
JUMP_SIZE     = 0.008           # ±0.8% jump magnitude

BARS_PER_DAY  = 78              # 09:30–16:00 ET, 5-min
TRADING_DAYS  = 252
YEARS         = 5

dt = 1.0 / (TRADING_DAYS * BARS_PER_DAY)
mu_bar    = ANNUAL_RETURN * dt
sigma_bar = ANNUAL_VOL * np.sqrt(dt)   # ≈ 0.00125 per bar

# ── Intraday vol multiplier (U-shape: high open & close) ─────────────────────
def intraday_vol_mult(bar_idx):
    """bar_idx 0-77 within trading day"""
    x = bar_idx / (BARS_PER_DAY - 1)
    # U-shape: high at open (0) and close (1), low in middle
    return 0.7 + 1.1 * (2 * (x - 0.5) ** 2)

# ── Build timestamps ──────────────────────────────────────────────────────────
def trading_timestamps(start_date, n_days):
    stamps = []
    d = start_date
    count = 0
    while count < n_days:
        if d.weekday() < 5:  # Mon-Fri
            for b in range(BARS_PER_DAY):
                minutes = 9 * 60 + 30 + b * 5
                h, m = divmod(minutes, 60)
                stamps.append(datetime(d.year, d.month, d.day, h, m))
            count += 1
        d += timedelta(days=1)
    return stamps

# ── Generate OHLCV ────────────────────────────────────────────────────────────
def generate():
    total_days = TRADING_DAYS * YEARS
    timestamps = trading_timestamps(datetime(2020, 1, 2), total_days)
    N = len(timestamps)

    close = np.empty(N)
    open_ = np.empty(N)
    high  = np.empty(N)
    low   = np.empty(N)
    vol   = np.empty(N, dtype=np.int64)

    price = START_PRICE

    for i, ts in enumerate(timestamps):
        bar_idx = i % BARS_PER_DAY
        vol_mult = intraday_vol_mult(bar_idx)
        σ = sigma_bar * vol_mult

        # Return for this bar
        z    = np.random.randn()
        jump = 0.0
        if np.random.rand() < JUMP_PROB:
            jump = np.random.choice([-1, 1]) * JUMP_SIZE * np.random.rand()
        r = mu_bar - 0.5 * σ**2 + σ * z + jump

        prev = price
        price = prev * np.exp(r)

        # OHLC with realistic wicks
        o = prev if bar_idx == 0 else prev
        c = price
        # intrabar noise for high/low
        noise_hi = abs(np.random.normal(0, σ * 0.6))
        noise_lo = abs(np.random.normal(0, σ * 0.6))
        h_val = max(o, c) * (1 + noise_hi)
        l_val = min(o, c) * (1 - noise_lo)

        open_[i] = round(o, 1)
        close[i]  = round(c, 1)
        high[i]   = round(h_val, 1)
        low[i]    = round(l_val, 1)
        vol[i]    = int(np.random.lognormal(10, 0.7))

    df = pd.DataFrame({
        'Open':   open_,
        'High':   high,
        'Low':    low,
        'Close':  close,
        'Volume': vol
    }, index=pd.DatetimeIndex(timestamps, name='Datetime'))

    return df

if __name__ == '__main__':
    cache = 'nas100_cache.pkl'
    print("Generating 5-year synthetic NAS100 5-min data...")
    df = generate()
    with open(cache, 'wb') as f:
        pickle.dump(df, f)
    print(f"Done — {len(df):,} bars saved to {cache}")
    print(f"Price range: {df['Close'].min():.0f} – {df['Close'].max():.0f}")
    print(f"Date range:  {df.index[0]} → {df.index[-1]}")
