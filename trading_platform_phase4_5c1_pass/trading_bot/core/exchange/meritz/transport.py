"""Allowlisted read-only REST. The sole POST is client-credentials authentication."""
from decimal import Decimal
import json
import math
import os
import re
from threading import RLock
from time import monotonic, sleep

import httpx

BASE = "https://openapi.imeritz.com:9443"
AUTH_CODES = {"EGW00121","EGW00123"}
READ = {
    "quote":("/market/v1/overseas/prices",{"0000"}),
    "book":("/market/v1/overseas/orderbook",{"0000"}),
    "days":("/market/v1/overseas/candles/days",{"0000"}),
    "minutes":("/market/v1/overseas/candles/minutes",{"0000"}),
    "market_days":("/reference/v1/overseas/market-days",{"5766","5820"}),
    "market_hours":("/reference/v1/overseas/market-hours",{"5766","5820"}),
    "deposit":("/accounts/v1/me/deposit",{"5766"}),
    "foreign":("/accounts/v1/me/overseas/currencies",{"5766","5820"}),
    "positions":("/accounts/v1/me/overseas/holdings",{"5762","5766","5820"}),
    "orderable":("/trading/v1/overseas/orders/estimate",{"5766","5820"}),
    "today":("/trading/v1/overseas/orders/today",{"5766","5820"}),
    "history":("/trading/v1/overseas/orders/history",{"5762","5766","5820"}),
    "detail":("/trading/v1/overseas/orders/detail",{"5766","5820"}),
    "pnl":("/accounts/v1/me/overseas/profit-loss",{"5762","5766","5820"}),
}


class MeritzError(RuntimeError):
    pass


class ReadOnlyTransport:
    def __init__(self, *, http=None, env=None, clock=monotonic, pause=sleep):
        self.http=http if http is not None else httpx.Client(timeout=10,follow_redirects=False)
        self.owns_http=http is None
        self.env=os.environ if env is None else env
        self.clock,self.pause=clock,pause
        self._lock=RLock()
        self._token=None
        self._expires=0
        self._last=float("-inf")
        self.halted=False

    def __enter__(self):
        return self

    def __exit__(self,*_):
        self._token=None
        if self.owns_http:
            self.http.close()

    def _call(self, method, path, **kw):
        if self.halted:
            raise MeritzError("transport halted")
        delay=1-(self.clock()-self._last)
        if delay>0:
            self.pause(delay)
        self._last=self.clock()
        try:
            res=self.http.request(method,BASE+path,follow_redirects=False,**kw)
            if len(res.content)>8_000_000:
                raise ValueError("oversized response")
            body=json.loads(res.content,parse_float=Decimal)
            if not isinstance(body,dict):
                raise ValueError("invalid response")
            return res.status_code,body
        except (httpx.HTTPError,ValueError):
            self.halted=True
            raise MeritzError("network or response failure; no automatic retry") from None

    def token(self):
        with self._lock:
            if self.halted:
                raise MeritzError("transport halted")
            if self._token is not None and self.clock()<self._expires:
                return self._token
            try:
                key=self.env["MERITZ_APP_KEY"]
                secret=self.env["MERITZ_APP_SECRET"]
                if not key or not secret:
                    raise ValueError
                issued=self.clock()
                status,payload=self._call("POST","/oauth2/token",
                     data={"grant_type":"client_credentials","client_id":key,
                           "client_secret":secret,"scope":"login"})
                ttl=float(payload["expires_in"])
                token=payload["access_token"]
                if status!=200 or not math.isfinite(ttl) or ttl<=0 or not isinstance(token,str) or not token:
                    raise ValueError
                self._expires=issued+ttl-min(60,ttl/2)
                if self._expires<=self.clock():
                    raise ValueError
                self._token=token
                return token
            except (KeyError,ValueError,TypeError,MeritzError,OverflowError):
                self.halted=True
                self._token=None
                raise MeritzError("authentication unavailable; transport halted") from None

    def response(self,name,params=None):
        path,codes=READ[name]
        with self._lock:
            mac=self.env.get("MERITZ_MAC_ADDRESS","")
            if not re.fullmatch("[0-9a-fA-F]{12}",mac):
                raise MeritzError("configured device MAC required for authorized read requests")
            for attempt in range(2):
                status,body=self._call("GET",path,params=params,headers={
                    "Authorization":"Bearer "+self.token(),"mac_address":mac})
                code=body.get("rsp_cd")
                if isinstance(code,str) and code in AUTH_CODES and attempt==0:
                    self._token=None
                    continue
                if status==200 and isinstance(code,str) and code in codes and "data" in body:
                    return body
                self.halted=True
                raise MeritzError("read rejected or malformed; transport halted")
            raise MeritzError("read unavailable")

    def get(self,name,params=None):
        body=self.response(name,params)
        return [] if body["rsp_cd"]=="5820" and body["data"] is None else body["data"]

    def pages(self,name,params=None):
        result,seen=[],set()
        params=dict(params or {})
        for _ in range(100):
            body=self.response(name,params)
            rows=body["data"]
            if rows is None and body["rsp_cd"]=="5820":
                rows=[]
            if not isinstance(rows,list) or not all(isinstance(r,dict) for r in rows):
                break
            result.extend(rows)
            flag=body.get("tr_cont","0")
            if flag=="0" and body["rsp_cd"]!="5762":
                return result
            key=body.get("tr_cont_key")
            if flag!="1" or not isinstance(key,str) or not key or key in seen:
                break
            seen.add(key)
            params.update(tr_cont="1",tr_cont_key=key)
        self.halted=True
        raise MeritzError("incomplete or repeated continuation page")
