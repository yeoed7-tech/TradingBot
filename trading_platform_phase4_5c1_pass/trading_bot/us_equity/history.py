"""Daily research input. Yahoo quote OHLC is split-only adjusted, not Adj Close."""
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
import csv
import json
import urllib.request

from trading_bot.core.portfolio.precision import dec

NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Session:
    day: date
    opens: datetime
    closes: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    split: Decimal = Decimal(1)
    dividend: Decimal = Decimal(0)


def fetch_inputs(directory, end):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    cutoff = int(datetime.combine(end, time(), NY).timestamp())
    sources = {
        k: f"https://query1.finance.yahoo.com/v8/finance/chart/{k}?period1=1265760000&period2={cutoff}&interval=1d&events=div,splits"
        for k in ("TQQQ", "QQQ")
    }
    sources["FX"] = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXKOUS"
    for name, url in sources.items():
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as response:
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError("oversized data")
        tmp = directory / (name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(directory / name)


def load_prices(path, symbol, calendar):
    j = json.loads(Path(path).read_bytes(), parse_float=Decimal)["chart"]["result"][0]
    if j["meta"]["symbol"] != symbol or j["meta"]["currency"] != "USD":
        raise ValueError("symbol/currency mismatch")
    day = lambda t: datetime.fromtimestamp(t, NY).date()
    dates = [day(t) for t in j["timestamp"]]
    expected = [s.date() for s in calendar.sessions_in_range(str(dates[0]), str(dates[-1]))]
    if dates != expected:
        raise ValueError("history has duplicate, missing, or non-session bars")
    e = j.get("events", {})
    splits = {day(x["date"]): dec(x["numerator"]) / dec(x["denominator"])
              for x in e.get("splits", {}).values()}
    dividends = {}
    for x in e.get("dividends", {}).values():
        d = day(x["date"])
        dividends[d] = dividends.get(d, Decimal(0)) + dec(x["amount"])
    if any(d not in dates for d in splits | dividends):
        raise ValueError("event outside supplied price calendar")
    quote = j["indicators"]["quote"][0]
    # Reverse later splits, including events after a given research subwindow.
    future = Decimal(1)
    bars = []
    for i in range(len(dates)-1, -1, -1):
        d = dates[i]
        o, h, l, c = [(dec(quote[k][i])*future).quantize(Decimal("0.0001")) for k in ("open","high","low","close")]
        split = splits.get(d, Decimal(1))
        if not 0 < l <= min(o,c) <= max(o,c) <= h or split < 1 or split != int(split):
            raise ValueError(f"invalid OHLC/split: {d}")
        bars.append(Session(d, calendar.session_open(str(d)).to_pydatetime(),
                            calendar.session_close(str(d)).to_pydatetime(),
                            o,h,l,c,split,dividends.get(d,Decimal(0))*future))
        future *= split
    return list(reversed(bars))


def load_fx(path):
    with open(path, newline="") as f:
        rows = csv.DictReader(f)
        return {date.fromisoformat(r["observation_date"]): dec(r["DEXKOUS"])
                for r in rows if r["DEXKOUS"] not in ("", ".")}
