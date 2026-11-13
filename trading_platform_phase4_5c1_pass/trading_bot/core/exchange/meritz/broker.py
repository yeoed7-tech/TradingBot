"""Observation-only brokerage adapter. No remote order mutation is possible."""
from dataclasses import dataclass
from decimal import Decimal

from .market import MarketDataClient, list_data, number, object_data
from .transport import MeritzError


@dataclass(frozen=True)
class OrderView:
    date: str
    number: str
    symbol: str
    side: str
    quantity: Decimal
    status: str


@dataclass(frozen=True)
class FillView:
    id: str
    order_number: str
    quantity: Decimal
    price: Decimal
    time_reported: str


class AccountClient:
    def __init__(self,transport):
        self.transport=transport

    def get_cash(self):
        return number(object_data(self.transport.get("deposit")),"tfam")

    def get_foreign_cash(self):
        return self._unique(list_data(self.transport.get("foreign")),"crcd","frcr_amt")

    def get_positions(self):
        rows=self.transport.pages("positions")
        return self._unique(rows,("ovrs_exch_vndr_idno","ovrs_stck_symb_iscd","crcd"),"rmnd_dqty")

    def realized_pnl(self,start,end,country_code):
        return self.transport.pages("pnl",{"oder_sta_date":start.strftime("%Y%m%d"),
            "oder_fin_date":end.strftime("%Y%m%d"),"ctcd":country_code})

    def get_orderable_amount(self):
        rows=list_data(self.transport.get("orderable",{"intg_marg_iqry_yn":"N"}))
        return self._unique(rows,"crcd","oder_crnc_oder_able_camt")

    @staticmethod
    def _unique(rows,key,value):
        result={}
        for row in rows:
            k=tuple(row[s] for s in key) if isinstance(key,tuple) else row[key]
            if k in result:
                raise MeritzError("ambiguous account rows")
            result[k]=number(row,value)
        return result


class OrderReader:
    def __init__(self,transport):
        self.transport=transport

    @staticmethod
    def normalize(row):
        status={"0":"ACCEPTED","1":"REJECTED","2":"REJECTED","3":"AUTO_CANCELLED","4":"NOT_ACCEPTED"}.get(
            str(row["ovrs_stck_oder_stat_cls_code"]),"UNKNOWN")
        side={"1":"SELL","2":"BUY"}.get(str(row["seln_byov_clcd"]))
        if side is None:
            raise MeritzError("unknown order side")
        qty=number(row,"oder_dqty" if "oder_dqty" in row else "odqt",positive=True)
        return OrderView(str(row["oder_date"]),str(row["oder_no"]),row["iscd"],side,qty,status)

    def get_orders(self):
        # Today endpoint has a continuation indicator but no published continuation inputs.
        body=self.transport.response("today",{"cntg_cls_code":"0","seln_byov_clcd":"0"})
        if body.get("tr_cont","0")!="0":
            raise MeritzError("today orders truncated; use history")
        if body["rsp_cd"]=="5820" and body["data"] is None:
            return []
        return [self.normalize(x) for x in list_data(body["data"])]

    def history(self,start,end):
        return self.transport.pages("history",{
            "oder_sta_date":start.strftime("%Y%m%d"),"oder_fin_date":end.strftime("%Y%m%d"),
            "cntg_cls_code":"0","seln_byov_clcd":"0"})

    def _detail(self,day,number_):
        rows=self.transport.pages("detail",{"oder_sta_date":day,"oder_no":number_})
        if any(str(x["oder_date"])!=day or str(x["oder_no"])!=number_ for x in rows):
            raise MeritzError("order identity mismatch")
        return rows

    def get_order(self,day,number_):
        rows=self._detail(day,number_)
        orders={self.normalize(x) for x in rows}
        if len(orders)!=1:
            raise MeritzError("order unknown or inconsistent")
        return orders.pop()

    def get_fills(self,day,number_):
        fills={}
        for row in self._detail(day,number_):
            fill_number=str(row["cntg_no"])
            if fill_number=="0":
                if number(row,"cntg_dqty")!=0:
                    raise MeritzError("missing execution identifier")
                continue
            key=f"{day}:{number_}:{fill_number}"
            fill=FillView(key,number_,number(row,"cntg_dqty",positive=True),
                          number(row,"cntg_crnc_prc",positive=True),row["cntg_ymdh"])
            if key in fills and fills[key]!=fill:
                raise MeritzError("conflicting execution response")
            fills[key]=fill
        return list(fills.values())


class MeritzBrokerAdapter:
    def __init__(self,transport):
        self.market=MarketDataClient(transport)
        self.account=AccountClient(transport)
        self.orders=OrderReader(transport)
        self.paused=True

    def get_quote(self,*args,**kwargs): return self.market.get_quote(*args,**kwargs)
    def get_orderbook(self,*args,**kwargs): return self.market.get_orderbook(*args,**kwargs)
    def get_cash(self): return self.account.get_cash()
    def get_foreign_cash(self): return self.account.get_foreign_cash()
    def get_positions(self): return self.account.get_positions()
    def get_orderable_amount(self): return self.account.get_orderable_amount()
    def get_order(self,*args): return self.orders.get_order(*args)
    def get_orders(self): return self.orders.get_orders()
    def get_fills(self,*args): return self.orders.get_fills(*args)

    def reconcile(self,expected):
        self.paused=True
        observed={"foreign":self.get_foreign_cash(),"positions":self.get_positions(),
                  "orders":self.get_orders()}
        if any(o.status=="UNKNOWN" for o in observed["orders"]) or observed!=expected:
            raise MeritzError("reconciliation mismatch or unknown order")
        # An observation match is not approval to submit orders.
        return observed

    @staticmethod
    def _write_disabled(*args,**kwargs):
        raise MeritzError("Meritz order submission disabled in this build")

    submit_buy=submit_sell=amend_order=cancel_order=_write_disabled
