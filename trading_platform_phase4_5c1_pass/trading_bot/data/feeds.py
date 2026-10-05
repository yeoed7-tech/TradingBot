"""Completed-bar feeds. Reconnect backfill updates indicators, never retro-fills."""
import asyncio
from datetime import datetime,timezone,timedelta
from typing import Protocol,AsyncIterator
from trading_bot.data.market_data import MarketDataEngine
from trading_bot.core.events.market import FeedEvent,FeedState,InvalidMarketData,validate_bar
from trading_bot.core.exchange.upbit_public import TIMEFRAMES,PublicDataUnavailable
import ccxt

class MarketDataFeed(Protocol):
    def __aiter__(self) -> AsyncIterator[FeedEvent]: ...

class HistoricalFeed:
    def __init__(self,frame,bar_seconds):
        self.data=MarketDataEngine(frame,bar_seconds)
        self.bar_seconds=bar_seconds
    def batches(self): return self.data.batches()
    async def __aiter__(self):
        for t,bars in self.batches():
            yield FeedEvent(t+timedelta(seconds=self.bar_seconds),FeedState.NORMAL,tuple(bars.values()))

class ReplayFeed:
    """Replay captured data/control events, including duplicate/error events.

    Event times remain unchanged; the consumer supplies a replay clock.
    """
    def __init__(self,events,delay=0):
        if delay<0: raise ValueError('delay must be nonnegative')
        self.events=tuple(events); self.delay=delay
    async def __aiter__(self):
        for event in self.events:
            if self.delay: await asyncio.sleep(self.delay)
            yield event

class RealtimeExchangeFeed:
    def __init__(self,public_data,config,*,clock=None,sleep=asyncio.sleep,quote_stream=None):
        self._public=public_data
        self.quote_stream=quote_stream
        self.metrics={"rest_requests":0,"gap_events":0,"stale_events":0,"duplicate_events":0,"normal_events":0}
        self.config=config
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.sleep=sleep
        self.step=TIMEFRAMES[config.timeframe]*1000
        self.last_ms=None
        self.start_ms=None
        self.failures=0
        self.state=FeedState.DISCONNECTED
        self.stopped=False

    def failure(self,state,reason):
        self.failures+=1
        if self.failures>=self.config.reconnect.max_consecutive_failures:
            state=FeedState.FAILED
        self.state=state
        if state==FeedState.GAP:self.metrics["gap_events"]+=1
        if state==FeedState.STALE_DATA:self.metrics["stale_events"]+=1
        return FeedEvent(self.clock(),state,reason=reason,decision_allowed=False)

    async def poll(self):
        if self.state==FeedState.FAILED:
            return FeedEvent(self.clock(),FeedState.FAILED,reason='latched feed failure',decision_allowed=False)
        now=self.clock()
        end=int(now.timestamp()*1000)//self.step*self.step
        if self.start_ms is None: self.start_ms=end-self.config.warmup_bars*self.step
        since=self.start_ms if self.last_ms is None else self.last_ms+self.step
        if (end-since)//self.step>self.config.max_gap_bars:
            return self.failure(FeedState.GAP,'gap exceeds configured recovery bound')
        try:
            self.metrics["rest_requests"]+=1
            bars=await self._public.candles(self.config.symbol,self.config.timeframe,since,end)
            by_time={}
            for b in bars:
                validate_bar(b)
                if b.symbol!=self.config.symbol: raise InvalidMarketData('bar symbol mismatch')
                ts=int(b.timestamp.timestamp()*1000)
                if ts%self.step: raise InvalidMarketData('unaligned bar')
                if ts<since or ts+self.step>end: continue # duplicates/unfinished candles
                if ts in by_time:
                    if by_time[ts]!=b: raise InvalidMarketData('conflicting duplicate')
                    self.metrics["duplicate_events"]+=1
                by_time[ts]=b
            expected=range(since,end,self.step)
            if any(t not in by_time for t in expected):
                return self.failure(FeedState.GAP,'missing candle; cursor unchanged, retry/backfill before trading')
            if self.quote_stream is None:
                self.metrics["rest_requests"]+=1
                quote=await self._public.order_book(self.config.symbol)
            else:
                quote=await self.quote_stream.next_quote()
            if quote.symbol!=self.config.symbol: raise InvalidMarketData('quote symbol mismatch')
            observed=self.clock()
            age=(observed-quote.timestamp).total_seconds()
            latest=end-self.step if by_time else self.last_ms
            candle_age=float('inf') if latest is None else observed.timestamp()-(latest+self.step)/1000
            if age < -self.config.clock_skew_tolerance:
                raise InvalidMarketData('quote is in the future')
            if age>self.config.quote_max_age or candle_age>self.config.stale_data_timeout:
                return self.failure(FeedState.STALE_DATA,'stale exchange timestamp or completed candle')
            recovered=self.failures>0
            self.failures=0
            self.state=FeedState.NORMAL
            self.metrics["normal_events"]+=1
            if by_time: self.last_ms=max(by_time)
            return FeedEvent(observed,self.state,tuple(by_time[t] for t in sorted(by_time)),quote,recovered=recovered)
        except InvalidMarketData as exc:
            return self.failure(FeedState.INVALID_DATA,str(exc))
        except Exception as exc:
            if isinstance(exc,asyncio.CancelledError):raise
            if self.quote_stream is not None:await self.quote_stream.close()
            return self.failure(FeedState.DISCONNECTED,f'{type(exc).__name__}: {str(exc)[:240]}')

    async def __aiter__(self):
        while not self.stopped:
            event=await self.poll()
            yield event
            if event.state==FeedState.FAILED: return
            delay=self.config.poll_interval
            if self.failures:
                delay=max(delay,min(self.config.reconnect.max_backoff,
                                    self.config.reconnect.base_backoff*2**min(self.failures-1,20)))
            await self.sleep(delay)
