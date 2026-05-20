import os
import pickle
import random
import numpy as np
import pandas as pd
import yfinance as yf
from flask import Flask, render_template, jsonify
from datetime import datetime

app = Flask(__name__)
APP_DIR    = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(APP_DIR, 'nas100_cache.pkl')
CACHE_TTL  = 3600  # 1 hour

# ---------------------------------------------------------------------------
# Indicator calculations
# ---------------------------------------------------------------------------

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def bollinger_bands(series, period=20, mult=2.0):
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    return mid + mult * std, mid, mid - mult * std

def keltner_channels(high, low, close, period=20, mult=1.5):
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    mid = ema(close, period)
    return mid + mult * atr, mid, mid - mult * atr

def _linreg_last(x):
    """Vectorised linear regression — returns last fitted value."""
    n = len(x)
    xi = np.arange(n, dtype=np.float64)
    xi_mean = (n - 1) / 2.0
    xi_var  = np.sum((xi - xi_mean) ** 2)
    if xi_var == 0:
        return x[-1]
    slope = np.sum((xi - xi_mean) * (x - x.mean())) / xi_var
    return slope * (n - 1) + (x.mean() - slope * xi_mean)

def squeeze_momentum(high, low, close, period=20, bb_mult=2.0, kc_mult=1.5):
    bb_u, bb_m, bb_l = bollinger_bands(close, period, bb_mult)
    kc_u, kc_m, kc_l = keltner_channels(high, low, close, period, kc_mult)

    sqz_on = (bb_l > kc_l) & (bb_u < kc_u)

    hh = high.rolling(period).max()
    ll = low.rolling(period).min()
    delta = close - (hh + ll) / 2

    mom = delta.rolling(period).apply(_linreg_last, raw=True)
    return mom, sqz_on

# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def flatten_columns(df):
    """Handle yfinance MultiIndex columns."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

def _try_live_download():
    """Attempt to download fresh data; returns DataFrame or None."""
    for ticker_sym in ["NQ=F", "^NDX", "QQQ"]:
        try:
            df = yf.download(ticker_sym, period="60d", interval="5m",
                             auto_adjust=True, progress=False)
            df = flatten_columns(df)
            df = df.dropna()
            if len(df) > 200:
                print(f"Got {len(df)} live candles from {ticker_sym}")
                return df
        except Exception as e:
            print(f"  {ticker_sym} failed: {e}")
    return None

def _load_or_generate_synthetic():
    """Load pre-generated synthetic data, or generate it on the fly."""
    gen_script = os.path.join(APP_DIR, 'generate_data.py')
    if os.path.exists(gen_script):
        import subprocess, sys
        subprocess.run([sys.executable, gen_script], check=True)
        with open(CACHE_FILE, 'rb') as f:
            return pickle.load(f)
    # Minimal inline fallback GBM
    import generate_data
    df = generate_data.generate()
    return df

def fetch_data():
    # 1. Use cached file if fresh enough
    if os.path.exists(CACHE_FILE):
        mtime = os.path.getmtime(CACHE_FILE)
        if (datetime.now().timestamp() - mtime) < CACHE_TTL:
            with open(CACHE_FILE, 'rb') as f:
                df = pickle.load(f)
            if len(df) > 200:
                print(f"Using cached data: {len(df):,} candles")
                return df

    # 2. Try live download
    print("Attempting live NAS100 data download...")
    df = _try_live_download()
    if df is not None:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(df, f)
        return df

    # 3. Fall back to synthetic data (pre-generated or generate now)
    print("Live data unavailable — using synthetic NAS100 data")
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'rb') as f:
            df = pickle.load(f)
        if len(df) > 200:
            return df
    return _load_or_generate_synthetic()

# ---------------------------------------------------------------------------
# Flashcard preparation
# ---------------------------------------------------------------------------

LOOKBACK = 150  # candles to show
LOOKAHEAD = 6   # 30 mins = 6 × 5-min candles

def _safe_list(series, idx_range):
    return [None if pd.isna(series.iloc[i]) else round(float(series.iloc[i]), 2)
            for i in idx_range]

def prepare_flashcard(df, end_idx):
    start_idx = max(0, end_idx - LOOKBACK)
    idx_range = range(start_idx, end_idx)

    close = df['Close']
    high = df['High']
    low = df['Low']
    open_ = df['Open']

    # Indicators on full series for accuracy, then slice
    ema_periods = [8, 9, 12, 34, 50, 72, 89, 200]
    ema_data = {p: ema(close, p) for p in ema_periods}
    bb_u, bb_m, bb_l = bollinger_bands(close)
    mom, sqz_on = squeeze_momentum(high, low, close)

    times = [df.index[i].isoformat() for i in idx_range]

    # Squeeze bar colours (LazyBear style)
    squeeze_colors = []
    prev_mom = 0.0
    for i in idx_range:
        m = mom.iloc[i]
        if pd.isna(m):
            squeeze_colors.append('#787b86')
            continue
        m = float(m)
        if m >= 0:
            color = '#00e676' if m >= prev_mom else '#26a69a'
        else:
            color = '#ff1744' if m <= prev_mom else '#ef9a9a'
        squeeze_colors.append(color)
        prev_mom = m

    return {
        'times': times,
        'open': _safe_list(open_, idx_range),
        'high': _safe_list(high, idx_range),
        'low': _safe_list(low, idx_range),
        'close': _safe_list(close, idx_range),
        'ema8': _safe_list(ema_data[8], idx_range),
        'ema9': _safe_list(ema_data[9], idx_range),
        'ema12': _safe_list(ema_data[12], idx_range),
        'ema34': _safe_list(ema_data[34], idx_range),
        'ema50': _safe_list(ema_data[50], idx_range),
        'ema89': _safe_list(ema_data[89], idx_range),
        'ema200': _safe_list(ema_data[200], idx_range),
        'bb_upper': _safe_list(bb_u, idx_range),
        'bb_mid': _safe_list(bb_m, idx_range),
        'bb_lower': _safe_list(bb_l, idx_range),
        'momentum': _safe_list(mom, idx_range),
        'squeeze_on': [bool(sqz_on.iloc[i]) if not pd.isna(sqz_on.iloc[i]) else False
                       for i in idx_range],
        'squeeze_colors': squeeze_colors,
    }

def get_answer_data(df, end_idx):
    if end_idx + LOOKAHEAD > len(df):
        return None

    current_price = float(df['Close'].iloc[end_idx - 1])
    future_price = float(df['Close'].iloc[end_idx + LOOKAHEAD - 1])
    pips = round(future_price - current_price, 1)

    future_range = range(end_idx - 1, end_idx + LOOKAHEAD)
    return {
        'pips': pips,
        'direction': 'BUY' if pips > 0 else 'SELL',
        'current_price': round(current_price, 1),
        'future_price': round(future_price, 1),
        'future_candles': {
            'times': [df.index[i].isoformat() for i in future_range],
            'open':  [round(float(df['Open'].iloc[i]), 2) for i in future_range],
            'high':  [round(float(df['High'].iloc[i]), 2) for i in future_range],
            'low':   [round(float(df['Low'].iloc[i]), 2) for i in future_range],
            'close': [round(float(df['Close'].iloc[i]), 2) for i in future_range],
        }
    }

# ---------------------------------------------------------------------------
# Global data cache
# ---------------------------------------------------------------------------

_df = None

def get_df():
    global _df
    if _df is None:
        _df = fetch_data()
    return _df

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/card')
def api_card():
    df = get_df()
    min_idx = 220
    max_idx = len(df) - LOOKAHEAD - 2

    if max_idx <= min_idx:
        return jsonify({'error': 'Not enough data (need > 230 candles)'}), 400

    end_idx = random.randint(min_idx, max_idx)
    chart_data = prepare_flashcard(df, end_idx)
    current_price = round(float(df['Close'].iloc[end_idx - 1]), 1)

    return jsonify({
        'card_id': end_idx,
        'chart_data': chart_data,
        'current_price': current_price,
        'timestamp': str(df.index[end_idx - 1]),
        'total_cards': max_idx - min_idx,
    })

@app.route('/api/answer/<int:card_id>')
def api_answer(card_id):
    df = get_df()
    answer = get_answer_data(df, card_id)
    if answer is None:
        return jsonify({'error': 'No future data available'}), 400
    return jsonify(answer)

if __name__ == '__main__':
    app.run(debug=True, port=5001, host='0.0.0.0')
