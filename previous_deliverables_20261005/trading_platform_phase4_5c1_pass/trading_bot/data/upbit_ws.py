"""Upbit PUBLIC orderbook stream with bounded latest-quote delivery."""
import asyncio
import json
import math
from datetime import datetime,timezone
from uuid import uuid4
from websockets.asyncio.client import connect
from trading_bot.core.events.market import Quote,InvalidMarketData

URL='wss://api.upbit.com/websocket/v1'

def parse_orderbook(raw,symbol):
    try:
        obj=json.loads(raw)
        code=symbol.split('/')[1]+'-'+symbol.split('/')[0]
        if obj['type']!='orderbook' or obj['code']!=code:raise ValueError('unexpected market/type')
        unit=obj['orderbook_units'][0]
        bid=float(unit['bid_price']);ask=float(unit['ask_price'])
        bid_size=float(unit['bid_size']);ask_size=float(unit['ask_size'])
        ts=int(obj['timestamp'])
        if not all(math.isfinite(x) for x in (bid,ask,bid_size,ask_size)) or bid<=0 or ask<bid or bid_size<0 or ask_size<0 or ts<=0:
            raise ValueError('invalid book')
        return Quote(symbol,datetime.fromtimestamp(ts/1000,timezone.utc),bid,ask,bid_size,ask_size)
    except (KeyError,IndexError,TypeError,ValueError,OverflowError) as exc:
        raise InvalidMarketData(f'malformed websocket orderbook: {type(exc).__name__}') from exc

class UpbitPublicQuoteStream:
    def __init__(self,symbol,*,connector=connect,timeout=12):
        self.symbol=symbol;self.connector=connector;self.timeout=timeout
        self.connection=None;self.reconnects=0;self.received=0;self.duplicates=0
        self.last_timestamp=None;self.latest=None;self._changed=asyncio.Event();self._reader=None
        self._error=None

    async def open(self):
        if self.connection is not None:await self.close()
        self.connection=await self.connector(URL,open_timeout=self.timeout,ping_interval=20,ping_timeout=20,max_queue=8)
        code=self.symbol.split('/')[1]+'-'+self.symbol.split('/')[0]
        await self.connection.send(json.dumps([{'ticket':str(uuid4())},
            {'type':'orderbook','codes':[code]}, {'format':'DEFAULT'}]))
        self.reconnects+=1;self._error=None;self.latest=None;self._changed.clear()
        self._reader=asyncio.create_task(self._read_forever())

    async def _read_forever(self):
        try:
            while True:
                raw=await self.connection.recv()
                quote=parse_orderbook(raw,self.symbol)
                self.received+=1
                if self.last_timestamp is not None and quote.timestamp<=self.last_timestamp:
                    self.duplicates+=1;continue
                self.last_timestamp=quote.timestamp
                self.latest=quote;self._changed.set()
        except asyncio.CancelledError:raise
        except Exception as exc:
            self._error=exc;self._changed.set()

    async def next_quote(self):
        if self.connection is None:await self.open()
        try:await asyncio.wait_for(self._changed.wait(),self.timeout)
        except BaseException:
            await self.close();raise
        if self._error is not None:
            err=self._error
            await self.close();raise err
        quote=self.latest
        self._changed.clear()
        return quote

    async def close(self):
        if self._reader:
            task=self._reader;self._reader=None;task.cancel()
            try:await task
            except asyncio.CancelledError:pass
        if self.connection is not None:
            ws=self.connection;self.connection=None
            await ws.close()
        self._changed.clear()
