"""Quote WebSocket; each connection stays paused until REST reconciliation."""
import asyncio
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from websockets.asyncio.client import connect
from .market import number
from .transport import MeritzError

WS="wss://openapi.imeritz.com:29443/websocket"
KST=ZoneInfo("Asia/Seoul")
TR="ohhts_exst_cntg"


class RealtimeClient:
    def __init__(self,broker,transport,*,connector=connect,now=lambda:datetime.now(timezone.utc)):
        self.broker,self.transport,self.connector,self.now=broker,transport,connector,now
        self.observing=False

    async def quotes(self,instrument,expected,*,timeout=15,max_age=30):
        self.observing=False
        key=f"{instrument.market}@{instrument.symbol}"
        try:
            token=await asyncio.to_thread(self.transport.token)
            async with self.connector(WS,open_timeout=10,close_timeout=3,max_size=65536,max_queue=8) as ws:
                await ws.send(json.dumps({"header":{"token":"Bearer "+token,"tr_type":"1"},
                                         "body":{"tr_cd":TR,"tr_key":key}}))
                await asyncio.to_thread(self.broker.reconcile,expected)
                last=None
                while True:
                    message=json.loads(await asyncio.wait_for(ws.recv(),timeout))
                    header,body=message["header"],message.get("body")
                    if header.get("rsp_cd") in ("0000","0") and not body:
                        continue
                    if header.get("tr_cd")!=TR or header.get("tr_key")!=key or not isinstance(body,dict):
                        raise MeritzError("unexpected realtime message")
                    if body.get("iscd") not in (instrument.symbol, f"{instrument.symbol}.{instrument.market}"):
                        raise MeritzError("unexpected realtime symbol")
                    if body.get("dely_yn")!="N":
                        raise MeritzError("delayed or unconfirmed realtime quote")
                    stamp=datetime.strptime(body["korea_date"]+body["korea_hour"],"%Y%m%d%H%M%S").replace(tzinfo=KST)
                    age=(self.now()-stamp).total_seconds()
                    if not -2<=age<=max_age or (last is not None and stamp<last):
                        raise MeritzError("stale or out-of-order quote")
                    price=number(body,"prpr",positive=True)
                    last=stamp
                    self.observing=True
                    yield stamp,price
        except Exception:
            raise MeritzError("realtime paused; reconnect and reconcile before observation") from None
        finally:
            self.observing=False
            self.broker.paused=True
