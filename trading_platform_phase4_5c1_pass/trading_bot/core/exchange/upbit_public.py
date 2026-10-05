"""ccxt.async_support Upbit public data, with GET/path allowlists at transport.

    No credentials accepted. Facade deliberately has no order methods.
"""
import asyncio
import ssl
import math
from collections import Counter
from urllib.parse import urlparse
import ccxt.async_support as ccxt
from trading_bot.core.events.models import Bar
from trading_bot.core.events.market import Quote,InvalidMarketData,utc_ms,positive,validate_bar

class PublicOnlyViolation(RuntimeError): pass
class PublicDataUnavailable(RuntimeError): pass

class GuardedUpbit(ccxt.upbit):
    PATHS={'market/all','ticker','orderbook','candles/{timeframe}/{unit}','candles/{timeframe}'}

    def __init__(self,timeout_ms=15000,*,trust_env=True,ca_bundle_path=None):
        # Honor the host's approved proxy and trust store. Verification stays ON.
        context=ssl.create_default_context(cafile=ca_bundle_path)
        super().__init__({'enableRateLimit':True,'timeout':timeout_ms,
                          'aiohttp_trust_env':trust_env,'ssl_context':context})
        self.audit=Counter()

    def sign(self,path,api='public',method='GET',params=None,headers=None,body=None):
        if api!='public' or method!='GET' or path not in self.PATHS:
            self.audit['blocked_requests']+=1
            raise PublicOnlyViolation('only allowlisted public market-data GETs are allowed')
        return super().sign(path,api,method,params or {},headers,body)

    async def fetch(self,url,method='GET',headers=None,body=None):
        u=urlparse(url)
        allowed=(u.path in {'/v1/market/all','/v1/ticker','/v1/orderbook'} or
                 u.path in {f'/v1/candles/minutes/{n}' for n in [1,3,5,10,15,30,60,240]} or
                 u.path=='/v1/candles/days')
        if (u.scheme!='https' or u.netloc!='api.upbit.com' or not allowed or method!='GET' or body is not None
            or any(k.lower()=='authorization' for k in (headers or {}))):
            self.audit['blocked_requests']+=1
            raise PublicOnlyViolation('transport rejected non-public request')
        self.audit['public_http_attempts']+=1
        self.audit['GET '+u.path]+=1
        return await super().fetch(url,method,headers,body)


TIMEFRAMES={'1m':60,'3m':180,'5m':300,'10m':600,'15m':900,'30m':1800,'1h':3600,'4h':14400,'1d':86400}


def normalize_candles(rows,symbol,seconds):
    by_time={}
    for row in rows:
        if len(row)<6: raise InvalidMarketData('short candle record')
        t=utc_ms(row[0])
        if int(t.timestamp()*1000)%(seconds*1000): raise InvalidMarketData('unaligned candle timestamp')
        b=Bar(t,symbol,*(float(v) for v in row[1:6]))
        validate_bar(b)
        if t in by_time and by_time[t]!=b: raise InvalidMarketData('conflicting duplicate candle')
        by_time[t]=b
    return [by_time[t] for t in sorted(by_time)]


def normalize_ticker(raw,symbol):
    if raw.get('symbol')!=symbol: raise InvalidMarketData('ticker symbol mismatch')
    return {'symbol':symbol,'timestamp':utc_ms(raw.get('timestamp')),'last':positive(raw.get('last'))}


def normalize_book(raw,symbol):
    if raw.get('symbol')!=symbol: raise InvalidMarketData('book symbol mismatch')
    bids,asks=raw.get('bids',[]),raw.get('asks',[])
    if not bids or not asks: raise InvalidMarketData('empty order book')
    for side in (bids,asks):
        for row in side:
            if len(row)<2: raise InvalidMarketData('invalid book level')
            positive(row[0]); positive(row[1])
    bid=max(bids,key=lambda r:r[0]); ask=min(asks,key=lambda r:r[0])
    return Quote(symbol,utc_ms(raw.get('timestamp')),float(bid[0]),float(ask[0]),float(bid[1]),float(ask[1]))

class UpbitPublicAdapter:
    __slots__=('__client','config','sleep','stats')

    def __init__(self,config,*,client=None,sleep=asyncio.sleep):
        # client injection is only a test seam. Production constructs GuardedUpbit.
        self.__client=client if client is not None else GuardedUpbit(
            int(config.request_timeout*1000),trust_env=config.network_trust_env,ca_bundle_path=config.ca_bundle_path)
        self.config=config
        self.sleep=sleep
        self.stats=Counter()

    async def _call(self,method,*args):
        if method not in {'load_markets','fetch_ticker','fetch_ohlcv','fetch_order_book'}:
            raise PublicOnlyViolation('public facade method denied')
        for attempt in range(self.config.reconnect.max_attempts):
            self.stats['api_attempts']+=1
            try:
                result=await asyncio.wait_for(getattr(self.__client,method)(*args),self.config.request_timeout)
                self.stats['api_successes']+=1
                return result
            except (ccxt.NetworkError,ccxt.RateLimitExceeded,asyncio.TimeoutError) as exc:
                self.stats['api_failures']+=1
                if attempt+1==self.config.reconnect.max_attempts:
                    raise PublicDataUnavailable(f'{method}: {type(exc).__name__}: {str(exc)[:160]}') from exc
                delay=min(self.config.reconnect.max_backoff,self.config.reconnect.base_backoff*2**attempt)
                await self.sleep(delay)

    async def ticker(self,symbol): return normalize_ticker(await self._call('fetch_ticker',symbol),symbol)
    async def order_book(self,symbol): return normalize_book(await self._call('fetch_order_book',symbol),symbol)

    async def market_metadata(self,symbol):
        markets=await self._call('load_markets')
        if symbol not in markets: raise InvalidMarketData('unknown market')
        m=markets[symbol]
        if m.get('spot') is not True or m.get('quote')!='KRW' or m.get('active') is False:
            raise InvalidMarketData('this adapter supports active Upbit KRW spot markets only')
        # Upbit public market/all does not supply private account-specific limits.
        # ccxt precision plus an explicit, sourced public-policy snapshot are exposed.
        return {'symbol':symbol,'base':m['base'],'quote':m['quote'],'spot':True,
                'precision':m.get('precision',{}),'limits':m.get('limits',{}),
                'account_access':False,'fee_source':'configured paper assumption',
                'rules_source':self.config.rules_source,
                'simulation_rules':self.config.market_rules.model_dump(),
                'effective_min_quantity':max(self.config.market_rules.min_quantity,self.config.market_rules.quantity_step),
                'precision_source':'ccxt descriptor; not authenticated order-chance endpoint'}

    async def fees(self,symbol):
        return {'symbol':symbol,'maker':self.config.fee_rate,'taker':self.config.fee_rate,
                'source':'configured paper assumption; no private fee endpoint called'}

    async def candles(self,symbol,timeframe,since_ms,until_ms):
        seconds=TIMEFRAMES[timeframe]; step=seconds*1000
        if since_ms%step or until_ms%step or since_ms>until_ms: raise ValueError('aligned [since,until) required')
        cursor=since_ms
        result={}
        pages=0
        while cursor<until_ms:
            pages+=1
            if pages>self.config.max_pages: raise PublicDataUnavailable('backfill page limit exceeded')
            count=min(self.config.page_size,(until_ms-cursor)//step)
            end=cursor+count*step
            # ccxt Upbit converts since + count * timeframe to exclusive `to`.
            rows=await self._call('fetch_ohlcv',symbol,timeframe,cursor,count)
            for b in normalize_candles(rows,symbol,seconds):
                ts=int(b.timestamp.timestamp()*1000)
                if cursor<=ts<end: result[ts]=b
            cursor=end  # advance by time window even when a no-trade interval is absent
        return [result[t] for t in sorted(result)]

    def audit(self):
        return {**dict(self.stats),'transport':dict(getattr(self.__client,'audit',{}))}

    async def close(self): await self.__client.close()
