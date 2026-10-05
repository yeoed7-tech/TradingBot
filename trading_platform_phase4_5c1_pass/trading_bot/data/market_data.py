"""Strict, synchronous multi-asset OHLCV feed. Never forward-fill missing prices."""
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
from trading_bot.core.events.models import Bar

COLUMNS = ['timestamp','symbol','open','high','low','close','volume']

def validate(frame: pd.DataFrame, bar_seconds: int) -> pd.DataFrame:
    if not set(COLUMNS).issubset(frame.columns):
        raise ValueError(f'CSV requires {COLUMNS}')
    f = frame[COLUMNS].copy()
    f['timestamp'] = pd.to_datetime(f.timestamp, utc=True, errors='raise')
    if f.empty or f.timestamp.isna().any() or f.symbol.isna().any() or (f.symbol.astype(str).str.len() == 0).any():
        raise ValueError('empty data, invalid timestamps or symbols')
    if f.duplicated(['timestamp','symbol']).any():
        raise ValueError('duplicate timestamp/symbol')
    for col in COLUMNS[2:]:
        f[col] = pd.to_numeric(f[col], errors='raise')
    if not np.isfinite(f[COLUMNS[2:]].to_numpy()).all():
        raise ValueError('non-finite market data')
    if (f[['open','high','low','close']] <= 0).any().any() or (f.volume < 0).any():
        raise ValueError('nonpositive price or negative volume')
    if ((f.high < f[['open','close','low']].max(axis=1)) | (f.low > f[['open','close','high']].min(axis=1))).any():
        raise ValueError('inconsistent OHLC')
    f = f.sort_values(['timestamp','symbol']).reset_index(drop=True)
    times = pd.DatetimeIndex(f.timestamp.unique())
    if len(times) < 2:
        raise ValueError('at least two bars required')
    if not (times.to_series().diff().dropna().dt.total_seconds() == bar_seconds).all():
        raise ValueError('missing bars or incorrect bar_seconds')
    if not (f.groupby('symbol').size() == len(times)).all():
        raise ValueError('assets must have identical calendars; no implicit forward filling')
    return f

class MarketDataEngine:
    def __init__(self, frame, bar_seconds):
        self.frame = validate(frame, bar_seconds)

    @classmethod
    def from_csv(cls, path, bar_seconds):
        warnings.warn('Universe/delisting history not verified: survivorship bias possible.', stacklevel=2)
        return cls(pd.read_csv(path), bar_seconds)

    def batches(self):
        for timestamp, frame in self.frame.groupby('timestamp', sort=True):
            yield timestamp.to_pydatetime(), {
                row.symbol: Bar(timestamp.to_pydatetime(), row.symbol, row.open, row.high, row.low, row.close, row.volume)
                for row in frame.itertuples(index=False)
            }

def synthetic_data(n=900, seed=42, symbols=('BTC/USDT','ETH/USDT')):
    """Deterministic artificial prices: tests/demonstration, NOT market evidence."""
    rng = np.random.default_rng(seed)
    rows = []
    for j, symbol in enumerate(symbols):
        prev = 20000 / (j + 1)
        for i, t in enumerate(pd.date_range('2022-01-01', periods=n, freq='D', tz='UTC')):
            op = prev * np.exp(rng.normal(0, 0.003))
            close = op * np.exp(0.001 * np.sin(i / 45) + rng.normal(0, 0.025))
            high = max(op, close) * (1 + rng.uniform(0, .02))
            low = min(op, close) * (1 - rng.uniform(0, .02))
            rows.append([t, symbol, op, high, low, close, rng.uniform(500,2000)])
            prev = close
    return pd.DataFrame(rows, columns=COLUMNS).sort_values(['timestamp','symbol']).reset_index(drop=True)
