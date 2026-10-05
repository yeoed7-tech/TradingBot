import asyncio
from datetime import datetime,timezone,timedelta
import pytest
from trading_bot.config.settings import PaperConfig
from trading_bot.data.feeds import RealtimeExchangeFeed,HistoricalFeed,ReplayFeed
from trading_bot.core.events.models import Bar
from trading_bot.core.events.market import Quote,FeedEvent,FeedState
from trading_bot.core.exchange.upbit_public import PublicDataUnavailable
from conftest import bars_frame

T=datetime(2024,1,1,tzinfo=timezone.utc)
class Clock:
    def __init__(self,now=None):self.now=now or T+timedelta(minutes=3,seconds=1)
    def __call__(self):return self.now
    def advance(self,seconds):self.now+=timedelta(seconds=seconds)

def candle(t,price=100): return Bar(t,'BTC/KRW',price,price,price,price,1000)

class PublicFake:
    def __init__(self,clock):
        self.clock=clock;self.missing=set();self.duplicate=False;self.incomplete=False;self.offline=False;self.stale=False
        self.requests=[]
    async def candles(self,symbol,timeframe,since,until):
        self.requests.append((since,until))
        if self.offline: raise PublicDataUnavailable('disconnected')
        bars=[candle(datetime.fromtimestamp(t/1000,timezone.utc)) for t in range(since,until,60000) if t not in self.missing]
        if self.duplicate and bars: bars.append(bars[-1])
        if self.incomplete:bars.append(candle(datetime.fromtimestamp(until/1000,timezone.utc)))
        return bars
    async def order_book(self,symbol):
        t=self.clock()-timedelta(seconds=60 if self.stale else 0)
        return Quote(symbol,t,99.9,100.1,100,100)


def test_normal_duplicates_and_unfinished_candle():
    async def run():
        clock=Clock();public=PublicFake(clock);public.duplicate=public.incomplete=True
        feed=RealtimeExchangeFeed(public,PaperConfig(warmup_bars=2),clock=clock)
        first=await feed.poll()
        assert first.state==FeedState.NORMAL and len(first.bars)==2
        again=await feed.poll()
        assert again.bars==()
        clock.advance(60)
        last=await feed.poll()
        assert len(last.bars)==1 and last.bars[0].timestamp==T+timedelta(minutes=3)
    asyncio.run(run())


def test_missing_disconnect_reconnect_backfill_and_cursor():
    async def run():
        clock=Clock();public=PublicFake(clock)
        feed=RealtimeExchangeFeed(public,PaperConfig(warmup_bars=2),clock=clock)
        first=await feed.poll();cursor=feed.last_ms
        clock.advance(120);public.offline=True
        failed=await feed.poll()
        assert failed.state==FeedState.DISCONNECTED and feed.last_ms==cursor
        public.offline=False; public.missing={cursor+60000}
        assert (await feed.poll()).state==FeedState.GAP
        assert feed.last_ms==cursor
        public.missing.clear()
        restored=await feed.poll()
        assert restored.state==FeedState.NORMAL and restored.recovered
        assert len(restored.bars)==2
        assert int(restored.bars[0].timestamp.timestamp()*1000)==cursor+60000
        assert (await feed.poll()).bars==()
    asyncio.run(run())


def test_stale_future_and_repeated_failure():
    async def run():
        clock=Clock();public=PublicFake(clock);public.stale=True
        cfg=PaperConfig(warmup_bars=2,reconnect={'max_consecutive_failures':2})
        feed=RealtimeExchangeFeed(public,cfg,clock=clock)
        assert (await feed.poll()).state==FeedState.STALE_DATA
        assert feed.last_ms is None
        assert (await feed.poll()).state==FeedState.FAILED
        public.stale=False
        assert (await feed.poll()).state==FeedState.FAILED
        assert feed.last_ms is None
    asyncio.run(run())


def test_gap_limit_and_invalid_price():
    async def run():
        clock=Clock();public=PublicFake(clock)
        cfg=PaperConfig(warmup_bars=2,max_gap_bars=3)
        feed=RealtimeExchangeFeed(public,cfg,clock=clock)
        await feed.poll(); clock.advance(240)
        assert (await feed.poll()).state==FeedState.GAP
        feed=RealtimeExchangeFeed(public,cfg,clock=clock)
        async def bad(*args): return [candle(clock()-timedelta(seconds=60),0)]
        public.candles=bad
        assert (await feed.poll()).state==FeedState.INVALID_DATA
    asyncio.run(run())


def test_historical_and_replay_contract():
    async def run():
        historical=HistoricalFeed(bars_frame([100,101,102]),86400)
        events=[e async for e in historical]
        assert len(events)==3
        replay=[e async for e in ReplayFeed(events)]
        assert events==replay
    asyncio.run(run())
