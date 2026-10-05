import asyncio
from datetime import datetime,timezone
from pathlib import Path
from trading_bot.core.exchange.upbit_public import UpbitPublicAdapter
from trading_bot.data.feeds import RealtimeExchangeFeed
from trading_bot.paper_trading.engine import PaperTradingEngine

async def run_public_paper(settings,strategy,out,duration=180,*,adapter_factory=UpbitPublicAdapter):
    if duration<=0: raise ValueError('duration must be positive')
    if settings.persistence.enabled and not settings.persistence.single_writer:
        raise ValueError('durable paper runner requires single writer fencing')
    durable=ledger=quote_stream=None
    lease_heartbeat=None
    feed=None
    from trading_bot.monitoring.rotating import configure_log
    logger=configure_log()
    logger.info('paper session starting',extra={'event':'STARTUP'})
    if settings.persistence.enabled:
        from trading_bot.persistence.ledger import PaperLedger,migrate
        from trading_bot.persistence.runtime import DurablePaperTrading
        url=settings.persistence.database_url
        if url.startswith('sqlite:///') and url!='sqlite:///:memory:':
            Path(url.removeprefix('sqlite:///')).parent.mkdir(parents=True,exist_ok=True)
        migrate(url)
        ledger=PaperLedger(url,settings.persistence.account)
        # A fresh strategy instance is needed when rebuilding its indicator state.
        from copy import deepcopy
        factory=lambda:deepcopy(strategy)
        durable=DurablePaperTrading(settings,factory,ledger)
        engine=durable.engine
        # The public REST warmup can outlast the lease TTL. Keep the writer
        # fenced from acquisition onward, before the feed iterator starts.
        lease_heartbeat=asyncio.create_task(durable._heartbeat_loop())
    else:
        engine=PaperTradingEngine(settings,strategy)
    adapter=adapter_factory(settings.paper_trading)
    extra={'started_at':datetime.now(timezone.utc).isoformat(),'duration_seconds':duration,
           'source':'Upbit public API via ccxt.async_support','integration_success':False}
    extra['writer_owner_id']=durable.lease.owner_id if durable and durable.lease else None
    extra['fencing_token']=durable.lease.token if durable and durable.lease else None
    try:
        async with asyncio.timeout(duration):
            metadata=await adapter.market_metadata(settings.paper_trading.symbol)
            extra['metadata']=metadata
            # Guard against precision changes silently invalidating quantity rounding.
            amount_step=metadata['precision'].get('amount')
            if amount_step is None or amount_step!=settings.paper_trading.market_rules.quantity_step:
                raise ValueError('configured quantity_step must match ccxt market amount precision')
            extra['ticker']=await adapter.ticker(settings.paper_trading.symbol)
            extra['fees']=await adapter.fees(settings.paper_trading.symbol)
            if settings.paper_trading.quote_source=="websocket":
                from trading_bot.data.upbit_ws import UpbitPublicQuoteStream
                quote_stream=UpbitPublicQuoteStream(settings.paper_trading.symbol,timeout=settings.paper_trading.request_timeout)
            feed=RealtimeExchangeFeed(adapter,settings.paper_trading,quote_stream=quote_stream)
            if durable: await durable.run(feed,heartbeat_task=lease_heartbeat)
            else: await engine.run(feed)
    except TimeoutError:
        extra['stop_reason']='configured observation duration reached'
        if engine.normal_events==0:
            from trading_bot.core.events.market import FeedState
            engine.pause(FeedState.FAILED,'no valid market event before deadline')
    except Exception as exc:
        from trading_bot.core.events.market import FeedState
        engine.pause(FeedState.FAILED,f'{type(exc).__name__}: {str(exc)[:240]}')
        extra['error']=f'{type(exc).__name__}: {str(exc)[:400]}'
        logger.error(extra['error'],extra={'event':'ORDER_ERROR'})
    finally:
        if lease_heartbeat:
            lease_heartbeat.cancel()
            try:await lease_heartbeat
            except asyncio.CancelledError:pass
        for order in engine.execution.orders: engine.execution.cancel(order,'paper_run_ended')
        if ledger:
            try:
                if durable and engine.last_bar and not durable.blocked:
                    from trading_bot.core.events.market import FeedEvent
                    ledger.checkpoint(durable.run_id,engine,FeedEvent(datetime.now(timezone.utc),engine.state))
                if durable and not durable.blocked:
                    extra['reconciliation_ok']=durable.reconciler.check()
                elif durable:extra['reconciliation_ok']=False
                from trading_bot.persistence.models import StrategyRun
                with ledger.Session.begin() as session:
                    if durable.lease:durable.lease.assert_owned(session)
                    run=session.get(StrategyRun,durable.run_id)
                    if run.status=='RUNNING':run.status='PAUSED'
                    run.end_time=datetime.now(timezone.utc).isoformat()
                ledger.event('SHUTDOWN','paper session stopped',run_id=durable.run_id)
            except Exception as exc:
                # A lost writer cannot modify account, risk, cursor, or run state.
                extra['shutdown_error']=type(exc).__name__
                logger.error('paper shutdown could not checkpoint',extra={'event':'DATABASE_ERROR'})
            finally:
                try:
                    if durable.lease:
                        extra['lease_token']=durable.lease.token
                        durable.lease.release()
                except Exception:pass
                ledger.close()
        if quote_stream:await quote_stream.close()
        if feed:extra["feed_metrics"]=feed.metrics
        if quote_stream:
            extra["websocket_reconnects"]=max(0,quote_stream.reconnects-1)
            extra["websocket_received"]=quote_stream.received
            extra["websocket_duplicate_events"]=quote_stream.duplicates
        await adapter.close()
        extra['finished_at']=datetime.now(timezone.utc).isoformat()
        extra['adapter_audit']=adapter.audit()
        extra.setdefault('lease_token',durable.lease.token if durable and durable.lease else None)
        transport=extra['adapter_audit'].get('transport',{})
        extra['real_order_http_requests']=sum(v for k,v in transport.items() if k.split(' ')[-1] in {'/v1/orders','/v1/order'})
        extra['real_cancel_http_requests']=sum(v for k,v in transport.items() if k.startswith('DELETE '))
        extra['private_http_requests']=sum(v for k,v in transport.items() if k.startswith(('POST ','DELETE ','PATCH ','PUT ')))
        extra['blocked_requests']=transport.get('blocked_requests',0)
        extra['integration_success']=(engine.normal_events>=2 and engine.processed_bars>0 and
                                      len(engine.portfolio.fills)>0 and not extra.get('error') and
                                      not extra.get('shutdown_error') and extra.get('reconciliation_ok',True) and
                                      str(engine.state)=='NORMAL')
        engine.save(out,extra)
        logger.info('paper session stopped',extra={'event':'SHUTDOWN','context':{'integration_success':extra['integration_success']}})
    return {**engine.summary(),**extra}
