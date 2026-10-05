import asyncio
from datetime import datetime,timezone
from unittest.mock import AsyncMock
import pytest
import ccxt
from trading_bot.config.settings import PaperConfig
from trading_bot.core.exchange.upbit_public import (UpbitPublicAdapter,GuardedUpbit,PublicOnlyViolation,
    PublicDataUnavailable,normalize_candles,normalize_ticker,normalize_book)
from trading_bot.core.exchange.public import UnavailableAccountAccess,AccountAccessUnavailable
from trading_bot.core.events.market import InvalidMarketData

MS=1704067200000

class Client:
    def __init__(self):
        self.calls=[];self.closed=False
        self.create_order=AsyncMock(side_effect=AssertionError('real order called'))
        self.cancel_order=AsyncMock(side_effect=AssertionError('real cancel called'))
    async def fetch_ohlcv(self,symbol,tf,since,limit):
        self.calls.append((symbol,tf,since,limit))
        return [[t,100,101,99,100,10] for t in range(since,since+limit*60000,60000)][::-1]
    async def fetch_ticker(self,symbol): return {'symbol':symbol,'timestamp':MS,'last':100}
    async def fetch_order_book(self,symbol): return {'symbol':symbol,'timestamp':MS,'bids':[[99,10]],'asks':[[101,10]]}
    async def load_markets(self): return {'BTC/KRW':{'symbol':'BTC/KRW','base':'BTC','quote':'KRW','spot':True,'active':True,'precision':{'amount':1e-8},'limits':{}}}
    async def close(self): self.closed=True


def test_normalization_and_conflicting_duplicate():
    row=[MS,100,101,99,100,10]
    bars=normalize_candles([row,row,[MS+60000,101,102,100,101,20]],'BTC/KRW',60)
    assert len(bars)==2 and bars[0].timestamp==datetime(2024,1,1,tzinfo=timezone.utc)
    with pytest.raises(InvalidMarketData): normalize_candles([row,[MS,100,101,99,101,10]],'BTC/KRW',60)
    with pytest.raises(InvalidMarketData): normalize_candles([[MS+1,100,101,99,100,1]],'BTC/KRW',60)
    assert normalize_ticker({'symbol':'BTC/KRW','timestamp':MS,'last':'100'},'BTC/KRW')['last']==100
    q=normalize_book({'symbol':'BTC/KRW','timestamp':MS,'bids':[[98,1],[99,2]],'asks':[[102,1],[101,2]]},'BTC/KRW')
    assert q.bid==99 and q.ask==101

@pytest.mark.parametrize('price',[0,-1,float('nan'),float('inf')])
def test_invalid_prices(price):
    with pytest.raises(InvalidMarketData): normalize_ticker({'symbol':'BTC','timestamp':MS,'last':price},'BTC')
    with pytest.raises(InvalidMarketData): normalize_candles([[MS,price,101,99,100,10]],'BTC',60)


def test_book_validation():
    with pytest.raises(InvalidMarketData): normalize_book({'symbol':'BTC','timestamp':MS,'bids':[],'asks':[]},'BTC')
    with pytest.raises(InvalidMarketData): normalize_book({'symbol':'BTC','timestamp':MS,'bids':[[102,1]],'asks':[[101,1]]},'BTC')
    with pytest.raises(InvalidMarketData): normalize_ticker({'symbol':'ETH','timestamp':MS,'last':100},'BTC')


def test_pagination_metadata_and_public_only_surface():
    async def run():
        client=Client();cfg=PaperConfig(page_size=2)
        a=UpbitPublicAdapter(cfg,client=client)
        bars=await a.candles('BTC/KRW','1m',MS,MS+5*60000)
        assert len(bars)==5
        assert [c[3] for c in client.calls]==[2,2,1]
        assert (await a.market_metadata('BTC/KRW'))['precision']['amount']==1e-8
        assert (await a.fees('BTC/KRW'))['taker']==cfg.fee_rate
        assert (await a.ticker('BTC/KRW'))['last']==100
        assert (await a.order_book('BTC/KRW')).mid==100
        for name in ['create_order','cancel_order','balances','positions','orders','fills']:
            assert not hasattr(a,name)
        with pytest.raises(PublicOnlyViolation): await a._call('create_order')
        assert client.create_order.await_count==client.cancel_order.await_count==0
        await a.close(); assert client.closed
    asyncio.run(run())


def test_backoff_rate_limit_and_timeout():
    async def run():
        client=Client(); waits=[]
        async def sleep(s): waits.append(s)
        client.fetch_ticker=AsyncMock(side_effect=[ccxt.RateLimitExceeded('429'),asyncio.TimeoutError(),{'symbol':'BTC/KRW','timestamp':MS,'last':100}])
        a=UpbitPublicAdapter(PaperConfig(),client=client,sleep=sleep)
        assert (await a.ticker('BTC/KRW'))['last']==100
        assert waits==[.5,1]
        assert a.stats['api_failures']==2
        client.fetch_ticker=AsyncMock(side_effect=ccxt.NetworkError('offline'))
        with pytest.raises(PublicDataUnavailable): await a.ticker('BTC/KRW')
        assert client.fetch_ticker.await_count==3
    asyncio.run(run())


def test_request_timeout_is_bounded():
    async def run():
        client=Client()
        async def slow(symbol): await asyncio.sleep(1)
        client.fetch_ticker=slow
        a=UpbitPublicAdapter(PaperConfig(request_timeout=.001,reconnect={'max_attempts':1}),client=client)
        with pytest.raises(PublicDataUnavailable): await a.ticker('BTC/KRW')
    asyncio.run(run())


def test_transport_blocks_private_and_mutating_requests():
    async def run():
        c=GuardedUpbit()
        try:
            for api,method,path in [('private','POST','orders'),('private','GET','accounts'),('public','DELETE','order'),('public','GET','orders')]:
                with pytest.raises(PublicOnlyViolation): c.sign(path,api,method,{})
            with pytest.raises(PublicOnlyViolation): await c.fetch('https://api.upbit.com/v1/orders','POST')
            with pytest.raises(PublicOnlyViolation): await c.fetch('https://example.com/v1/ticker')
            with pytest.raises(PublicOnlyViolation): await c.fetch('https://api.upbit.com/v1/ticker',headers={'Authorization':'x'})
            assert c.audit.get('public_http_attempts',0)==0
            signed=c.sign('ticker','public','GET',{'markets':'KRW-BTC'})
            assert signed['method']=='GET' and '/v1/ticker?' in signed['url']
        finally: await c.close()
    asyncio.run(run())


def test_unavailable_account_port_is_explicit():
    async def run():
        port=UnavailableAccountAccess()
        for name,args in [('balances',()),('positions',()),('orders',()),('fills',('id',)),('order_status',('id',))]:
            with pytest.raises(AccountAccessUnavailable): await getattr(port,name)(*args)
    asyncio.run(run())


def test_ccxt_real_parser_guarded_transport_to_paper(monkeypatch):
    """Actual ccxt methods/parsers; HTTP transport only is a deterministic fixture."""
    from ccxt.async_support.base.exchange import Exchange
    from urllib.parse import urlparse,parse_qs
    from datetime import timedelta
    from test_phase3_feed import Clock,T
    from conftest import Schedule
    from trading_bot.config.settings import Settings
    from trading_bot.data.feeds import RealtimeExchangeFeed
    from trading_bot.paper_trading.engine import PaperTradingEngine
    clock=Clock();seen=[];price=[100.]
    async def fixture_http(self,url,method='GET',headers=None,body=None):
        u=urlparse(url);q=parse_qs(u.query);seen.append((method,u.path))
        now=int(clock().timestamp()*1000)
        if u.path=='/v1/market/all': return [{'market':'KRW-BTC','korean_name':'비트코인','english_name':'Bitcoin'}]
        if u.path=='/v1/ticker': return [{'market':'KRW-BTC','timestamp':now,'trade_timestamp':now,'trade_price':price[0]}]
        if u.path=='/v1/orderbook': return [{'market':'KRW-BTC','timestamp':now,'orderbook_units':[
            {'bid_price':price[0]-.1,'ask_price':price[0]+.1,'bid_size':100,'ask_size':100}]}]
        if u.path=='/v1/candles/minutes/1':
            end=datetime.fromisoformat(q['to'][0].replace('Z','+00:00'))
            count=int(q['count'][0]); result=[]
            for i in range(1,count+1):
                t=end-timedelta(minutes=i)
                result.append({'market':'KRW-BTC','candle_date_time_utc':t.strftime('%Y-%m-%dT%H:%M:%S'),
                    'timestamp':int(t.timestamp()*1000),'opening_price':price[0],'high_price':price[0],
                    'low_price':price[0],'trade_price':price[0],'candle_acc_trade_volume':1000})
            return result
        raise AssertionError('unexpected HTTP endpoint: '+url)
    monkeypatch.setattr(Exchange,'fetch',fixture_http)
    async def run():
        cfg=Settings.model_validate({'risk':{'fixed_fraction':.5,'max_symbol_weight':.5,'max_slippage_bps':1000},
            'execution':{'max_volume_participation':1},
            'paper_trading':{'starting_cash':1000,'warmup_bars':2,'max_book_participation':1,
                'market_rules':{'min_notional':0,'quantity_step':1e-8,'price_tick':.01}}})
        transport=GuardedUpbit()
        transport.create_order=AsyncMock(side_effect=AssertionError('private create'))
        transport.cancel_order=AsyncMock(side_effect=AssertionError('private cancel'))
        a=UpbitPublicAdapter(cfg.paper_trading,client=transport)
        try:
            metadata=await a.market_metadata('BTC/KRW')
            assert metadata['precision']['amount']==1e-8
            assert (await a.ticker('BTC/KRW'))['last']==100
            feed=RealtimeExchangeFeed(a,cfg.paper_trading,clock=clock)
            e=PaperTradingEngine(cfg,Schedule([None,.2,0]),clock=clock)
            e.consume(await feed.poll());clock.advance(1);e.consume(await feed.poll())
            assert len(e.portfolio.fills)==1
            clock.advance(60);price[0]=110;e.consume(await feed.poll())
            clock.advance(1);e.consume(await feed.poll())
            assert len(e.portfolio.fills)>=2
            assert e.portfolio.quantity('BTC/KRW')==0
            assert transport.create_order.await_count==transport.cancel_order.await_count==0
            assert all(method=='GET' and 'orders' not in path for method,path in seen)
            assert transport.audit['public_http_attempts']==len(seen)>4
        finally: await a.close()
    asyncio.run(run())


def test_production_client_honors_environment_and_preserves_tls_verification():
    import ssl
    async def run():
        client=GuardedUpbit()
        try:
            assert client.aiohttp_trust_env is True
            assert client.verify is True
            assert isinstance(client.ssl_context,ssl.SSLContext)
            assert client.ssl_context.verify_mode==ssl.CERT_REQUIRED
            assert client.ssl_context.check_hostname is True
            assert not client.apiKey and not client.secret
        finally:await client.close()
    asyncio.run(run())


def test_bad_custom_ca_fails_without_insecure_fallback(tmp_path):
    with pytest.raises((FileNotFoundError,OSError)):
        GuardedUpbit(ca_bundle_path=str(tmp_path/'missing-ca.pem'))
