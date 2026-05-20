"""
Build a single self-contained HTML flashcard file with embedded chart data.
Pre-computes ALL indicators once, then slices per card — fast.
"""
import os, sys, json, pickle, random
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import (get_df, ema, bollinger_bands, keltner_channels,
                 squeeze_momentum, LOOKBACK, LOOKAHEAD, _safe_list)

NUM_CARDS = 300

def precompute_all(df):
    """Compute every indicator once on the full series."""
    print("  Computing indicators on full dataset...")
    close = df['Close']
    high  = df['High']
    low   = df['Low']

    emas = {p: ema(close, p) for p in [8,9,12,34,50,89,200]}
    bb_u, bb_m, bb_l = bollinger_bands(close)
    mom, sqz_on = squeeze_momentum(high, low, close)
    print("  Done.")
    return dict(emas=emas, bb_u=bb_u, bb_m=bb_m, bb_l=bb_l, mom=mom, sqz_on=sqz_on)

def session_start(df, end_idx):
    """Return the index of the first bar of the current trading day."""
    cur_date = df.index[end_idx - 1].date()
    for i in range(end_idx - 1, max(0, end_idx - 90), -1):
        if df.index[i].date() != cur_date:
            return i + 1
    return max(0, end_idx - 78)

DISPLAY_BARS = 48   # exactly 48 candles shown (4 hours of 5-min data)

def build_card(df, end_idx, ind):
    # Display window: last 48 bars, but not before today's session open
    sess_start   = session_start(df, end_idx)
    display_start = max(sess_start, end_idx - DISPLAY_BARS)
    idx_range    = range(display_start, end_idx)

    times = [df.index[i].isoformat() for i in idx_range]

    # Squeeze colours (LazyBear style)
    squeeze_colors, prev_mom = [], 0.0
    for i in idx_range:
        m = ind['mom'].iloc[i]
        if pd.isna(m):
            squeeze_colors.append('#787b86'); continue
        m = float(m)
        if m >= 0:  c = '#00e676' if m >= prev_mom else '#26a69a'
        else:       c = '#ff1744' if m <= prev_mom else '#ef9a9a'
        squeeze_colors.append(c); prev_mom = m

    chart = dict(
        times=times,
        open =_safe_list(df['Open'],  idx_range),
        high =_safe_list(df['High'],  idx_range),
        low  =_safe_list(df['Low'],   idx_range),
        close=_safe_list(df['Close'], idx_range),
        # Only EMA cloud pairs needed
        ema8 =_safe_list(ind['emas'][8],  idx_range),
        ema9 =_safe_list(ind['emas'][9],  idx_range),
        ema12=_safe_list(ind['emas'][12], idx_range),
        ema34=_safe_list(ind['emas'][34], idx_range),
        momentum      =_safe_list(ind['mom'],    idx_range),
        squeeze_on    =[bool(ind['sqz_on'].iloc[i]) if not pd.isna(ind['sqz_on'].iloc[i]) else False
                        for i in idx_range],
        squeeze_colors=squeeze_colors,
    )

    current_price = round(float(df['Close'].iloc[end_idx - 1]), 1)
    future_price  = round(float(df['Close'].iloc[end_idx + LOOKAHEAD - 1]), 1)
    future_range  = range(end_idx - 1, end_idx + LOOKAHEAD)
    answer = dict(
        pips          = round(future_price - current_price, 1),
        direction     = 'BUY' if future_price >= current_price else 'SELL',
        current_price = current_price,
        future_price  = future_price,
        future_candles= dict(
            times=[df.index[i].isoformat() for i in future_range],
            open =[round(float(df['Open'].iloc[i]),  2) for i in future_range],
            high =[round(float(df['High'].iloc[i]),  2) for i in future_range],
            low  =[round(float(df['Low'].iloc[i]),   2) for i in future_range],
            close=[round(float(df['Close'].iloc[i]), 2) for i in future_range],
        )
    )

    return dict(
        id=end_idx,
        timestamp=str(df.index[end_idx - 1]),
        current_price=current_price,
        chart=chart,
        answer=answer,
    )

def main():
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nas100_flashcards.html')
    print(f"Loading data...")
    df  = get_df()
    ind = precompute_all(df)

    min_idx = 220
    max_idx = len(df) - LOOKAHEAD - 2

    # Stratified sampling across full date range
    step       = (max_idx - min_idx) // NUM_CARDS
    candidates = list(range(min_idx, max_idx, max(step, 1)))
    random.shuffle(candidates)
    indices = candidates[:NUM_CARDS]

    print(f"Building {NUM_CARDS} cards...")
    cards = []
    for i, end_idx in enumerate(indices):
        cards.append(build_card(df, end_idx, ind))
        if (i+1) % 60 == 0:
            print(f"  {i+1}/{NUM_CARDS}...")

    print("Embedding into HTML...")
    tpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'standalone_template.html')
    with open(tpl_path, encoding='utf-8') as f:
        template = f.read()

    cards_json = json.dumps(cards, ensure_ascii=False, separators=(',', ':'))
    html = template.replace('__CARDS_JSON__', cards_json)

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)

    kb = os.path.getsize(out_path) / 1024
    print(f"Done → {out_path}  ({kb:.0f} KB)")
    print("Open this file in any browser — no server needed.")

if __name__ == '__main__':
    main()
