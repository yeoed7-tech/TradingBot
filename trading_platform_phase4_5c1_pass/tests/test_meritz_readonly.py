import asyncio
from datetime import datetime, timezone
from decimal import Decimal as D
import json

import httpx
import pytest

from trading_bot.core.exchange.meritz.broker import MeritzBrokerAdapter
from trading_bot.core.exchange.meritz.market import Instrument
from trading_bot.core.exchange.meritz.realtime import RealtimeClient
from trading_bot.core.exchange.meritz.transport import MeritzError, ReadOnlyTransport


ENV={"MERITZ_APP_KEY":"mock-key","MERITZ_APP_SECRET":"mock-secret","MERITZ_MAC_ADDRESS":"000000000001",
     "MERITZ_LIVE_TRADING":"true"}
I=Instrument("TQQQ","OQ","0537","fixture")


def make_transport(handler):
    return ReadOnlyTransport(http=httpx.Client(transport=httpx.MockTransport(handler)),
                             env=ENV,pause=lambda _:None)


def token():
    return httpx.Response(200,json={"expires_in":60,"access_token":"mock-token"})


def test_master_unique(tmp_path):
    p=tmp_path/"master"
    p.write_bytes(b"OQ`TQQQ`ETF`ProShares`1`0537`\n")
    assert Instrument.from_master(p,"TQQQ").vendor=="0537"
    p.write_bytes(p.read_bytes()*2)
    with pytest.raises(ValueError):
        Instrument.from_master(p,"TQQQ")


def test_auth_refresh_quote_and_write_allowlist():
    requests=[]
    def handler(r):
        requests.append((r.method,r.url.path))
        if r.method=="POST":
            assert r.url.path=="/oauth2/token" and b"scope=login" in r.content
            return token()
        if len(requests)==2:
            return httpx.Response(500,json={"rsp_cd":"EGW00121"})
        return httpx.Response(200,json={"rsp_cd":"0000","data":{"iscd":"TQQQ","crnc_code":"USD",
            "prpr":"50.22","shnu_aspr_unit":"0","shnu_oder_qty_unit":"1"}})
    b=MeritzBrokerAdapter(make_transport(handler))
    q=b.get_quote(I)
    assert q.price==D("50.22") and not q.rules_confirmed and q.delayed
    assert [m for m,_ in requests]==["POST","GET","POST","GET"]
    for operation in (b.submit_buy,b.submit_sell,b.amend_order,b.cancel_order):
        with pytest.raises(MeritzError,match="disabled"):
            operation(I)
    assert len(requests)==4


def test_preexpiry_refresh():
    now=[0]
    calls=[]
    def handler(r):
        calls.append(r)
        return token()
    t=make_transport(handler); t.clock=lambda:now[0]
    t.token(); now[0]=20; t.token(); assert len(calls)==1
    now[0]=31; t.token(); assert len(calls)==2


def test_timeout_latches_and_censors():
    calls=[]
    def handler(r):
        calls.append(r)
        if r.method=="POST":
            return token()
        raise httpx.ReadTimeout("do not echo secret",request=r)
    b=MeritzBrokerAdapter(make_transport(handler))
    with pytest.raises(MeritzError,match="no automatic retry") as err:
        b.get_quote(I)
    assert "secret" not in str(err.value)
    with pytest.raises(MeritzError,match="halted"):
        b.get_quote(I)
    assert len(calls)==2


def test_normalize_account_order_and_duplicate_fill():
    row={"oder_date":"20261112","oder_no":"42","iscd":"TQQQ.OQ","seln_byov_clcd":"2",
         "oder_dqty":"10","ovrs_stck_oder_stat_cls_code":"1","cntg_no":"13","cntg_dqty":"4",
         "cntg_crnc_prc":"51.25","cntg_ymdh":"2026-11-12 10:00:00"}
    def handler(r):
        if r.method=="POST":
            return token()
        if r.url.path.endswith("currencies"):
            data=[{"crcd":"USD","frcr_amt":"101.2345"}]
        elif r.url.path.endswith("holdings"):
            data=[{"ovrs_exch_vndr_idno":"0537","ovrs_stck_symb_iscd":"TQQQ","crcd":"USD","rmnd_dqty":"4"}]
        else:
            data=[row,row]
        return httpx.Response(200,json={"rsp_cd":"5766","data":data})
    b=MeritzBrokerAdapter(make_transport(handler))
    assert b.get_foreign_cash()=={"USD":D("101.2345")}
    assert b.get_positions()=={("0537","TQQQ","USD"):D(4)}
    assert b.get_order("20261112","42").status=="REJECTED"
    fills=b.get_fills("20261112","42")
    assert len(fills)==1 and fills[0].quantity==4
    with pytest.raises(MeritzError,match="mismatch"):
        b.reconcile({})
    assert b.paused


def test_pagination_repeated_cursor_halts():
    def handler(r):
        if r.method=="POST":
            return token()
        return httpx.Response(200,json={"rsp_cd":"5766","data":[],"tr_cont":"1","tr_cont_key":"same"})
    b=MeritzBrokerAdapter(make_transport(handler))
    with pytest.raises(MeritzError,match="continuation"):
        b.get_positions()


def test_ws_reconnect_reconciles_and_stale_pauses():
    reconciled=[]
    class Broker:
        paused=True
        def reconcile(self,expected):
            reconciled.append(expected)
    class Transport:
        def token(self): return "fake"
    class Socket:
        async def __aenter__(self): return self
        async def __aexit__(self,*_): pass
        async def send(self,msg):
            assert json.loads(msg)["body"]["tr_key"]=="OQ@TQQQ"
        async def recv(self):
            return json.dumps({"header":{"tr_cd":"ohhts_exst_cntg","tr_key":"OQ@TQQQ"},"body":{
                "iscd":"TQQQ","dely_yn":"0","korea_date":"20261113","korea_hour":"010000","prpr":"50"}})
    async def test():
        current=[datetime(2026,11,12,16,0,1,tzinfo=timezone.utc)]
        r=RealtimeClient(Broker(),Transport(),connector=lambda *a,**k:Socket(),now=lambda:current[0])
        async with __import__("contextlib").aclosing(r.quotes(I,{"first":True})) as stream:
            assert (await anext(stream))[1]==50 and r.observing
        assert not r.observing
        current[0]=datetime(2026,11,12,16,1,1,tzinfo=timezone.utc)
        with pytest.raises(MeritzError,match="paused"):
            await anext(r.quotes(I,{"second":True}))
        assert not r.observing and len(reconciled)==2
    asyncio.run(test())


def test_malformed_or_rejected_quote_is_not_a_success():
    def handler(r):
        if r.method=="POST":
            return token()
        return httpx.Response(200,json={"rsp_cd":"0760","data":{"prpr":"100"}})
    t=make_transport(handler)
    with pytest.raises(MeritzError,match="read rejected"):
        MeritzBrokerAdapter(t).get_quote(I)
    assert t.halted


def test_missing_credentials_makes_no_request():
    def handler(_):
        pytest.fail("unexpected request")
    t=make_transport(handler); t.env={}
    with pytest.raises(MeritzError):
        t.token()
    assert t.halted
