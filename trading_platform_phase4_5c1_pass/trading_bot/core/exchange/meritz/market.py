"""Public instrument file and authenticated, read-only market data."""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from trading_bot.core.portfolio.precision import dec

MASTER_URL = "https://openapi.imeritz.com/stock-info/download/exst"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    market: str
    vendor: str
    name: str

    @classmethod
    def from_master(cls, path, symbol):
        matches = []
        for raw in Path(path).read_bytes().splitlines():
            fields = raw.split(b"`")
            if len(fields) >= 6 and fields[1] == symbol.encode("ascii"):
                market, sym, name = (x.decode("cp949") for x in fields[:3])
                vendor = fields[5].decode("ascii")
                if not market.isalnum() or len(vendor)!=4 or not vendor.isdigit():
                    raise ValueError("invalid Meritz master identifiers")
                matches.append(cls(sym,market,vendor,name))
        if len(matches)!=1:
            raise ValueError("instrument missing or ambiguous in Meritz master")
        return matches[0]

    def query(self, *, delayed):
        return {"mrkt_div_code":"OV","mrkt_cls_code":self.market,"iscd":self.symbol,
                "dely_rltm_cls_code":"1" if delayed else "0"}


def object_data(data):
    if not isinstance(data,dict):
        raise ValueError("expected a Meritz object")
    return data


def list_data(data):
    if not isinstance(data,list) or not all(isinstance(x,dict) for x in data):
        raise ValueError("expected a Meritz row array")
    return data


def number(row,key,*,positive=False):
    n=dec(row[key])
    if positive and n<=0:
        raise ValueError("missing or nonpositive market value")
    return n


@dataclass(frozen=True)
class Quote:
    symbol: str
    currency: str
    price: Decimal
    buy_tick: Decimal | None
    sell_tick: Decimal | None
    buy_unit: Decimal | None
    sell_unit: Decimal | None
    sell_only: bool | None
    delayed: bool
    received_at: datetime

    @property
    def rules_confirmed(self):
        return all(x is not None and x>0 for x in (self.buy_tick,self.sell_tick,self.buy_unit,self.sell_unit))


class MarketDataClient:
    def __init__(self, transport):
        self.transport=transport

    def get_quote(self,instrument,*,delayed=True):
        x=object_data(self.transport.get("quote",instrument.query(delayed=delayed)))
        if x.get("iscd") not in (instrument.symbol, f"{instrument.symbol}.{instrument.market}"):
            raise ValueError("quote symbol mismatch")
        currency=x["crnc_code"]
        if len(currency)!=3 or not currency.isalpha():
            raise ValueError("invalid quote currency")
        def rule(k):
            n=dec(x[k]) if x.get(k) not in (None,"") else None
            return n if n is not None and n>0 else None
        sell_only={"Y":True,"N":False}.get(x.get("sell_only"))
        return Quote(instrument.symbol,currency,number(x,"prpr",positive=True),
                     rule("shnu_aspr_unit"),rule("seln_aspr_unit"),
                     rule("shnu_oder_qty_unit"),rule("seln_oder_qty_unit"),
                     sell_only,delayed,datetime.now(timezone.utc))

    def get_orderbook(self,instrument,*,delayed=True):
        x=object_data(self.transport.get("book",instrument.query(delayed=delayed)))
        bid,ask=number(x,"bidp1",positive=True),number(x,"askp1",positive=True)
        if bid>ask:
            raise ValueError("crossed quote")
        return {"symbol":instrument.symbol,"bid":bid,"ask":ask,"delayed":delayed}

    def days(self,instrument,start,end,*,delayed=True):
        if not isinstance(start,date) or not isinstance(end,date) or end<start:
            raise ValueError("invalid date range")
        query=instrument.query(delayed=delayed)
        query.update({"mod_stpr_cls_code":"1","from":start.strftime("%Y%m%d"),"to":end.strftime("%Y%m%d")})
        rows=list_data(self.transport.get("days",query))
        return [{"date":datetime.strptime(r["date"],"%Y%m%d").date(),
                 **{k:number(r,v,positive=True) for k,v in
                    (("open","oprc"),("high","hprc"),("low","lprc"),("close","prpr"))},
                 "volume":number(r,"acml_vol")} for r in reversed(rows)]

    def minutes(self,instrument,seconds=60,*,delayed=True):
        if not isinstance(seconds,int) or seconds<=0:
            raise ValueError("invalid bar interval")
        return list_data(self.transport.get("minutes",{
            **instrument.query(delayed=delayed),"hour_cls_code":str(seconds)}))

    def market_days(self,instrument):
        return self.transport.get("market_days",{"ovrs_exch_vndr_idno":instrument.vendor})

    def market_hours(self):
        return self.transport.get("market_hours")
