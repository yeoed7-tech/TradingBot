from trading_bot.core.events.models import Status

class MockExchange:
    """Offline contract double; actual simulated fills belong to SimulationBroker."""
    def __init__(self,bars,fee_rate=.001):
        self.bars=bars
        self.fee_rate=fee_rate
        self.orders={}

    async def ticker(self,symbol):
        b=self.bars[symbol][-1]
        return {'symbol':symbol,'last':b.close,'timestamp':b.timestamp.isoformat()}

    async def ohlcv(self,symbol,since,limit):
        return [[int(b.timestamp.timestamp()*1000),b.open,b.high,b.low,b.close,b.volume]
                for b in self.bars[symbol] if b.timestamp.timestamp()*1000>=since][:limit]

    async def order_book(self,symbol):
        p=(await self.ticker(symbol))['last']
        return {'bids':[[p*.999,1.]],'asks':[[p*1.001,1.]]}

    async def balances(self): return {'cash':100000.}
    async def positions(self): return []
    async def fees(self,symbol): return {'symbol':symbol,'maker':self.fee_rate,'taker':self.fee_rate}

    async def create_order(self,order):
        if order.id not in self.orders:
            self.orders[order.id]={'id':order.id,'symbol':order.symbol,'status':Status.SUBMITTED.value}
        return dict(self.orders[order.id])

    async def cancel_order(self,order_id):
        o=self.orders[order_id]
        if o['status'] not in {Status.FILLED.value,Status.REJECTED.value,Status.FAILED.value}:
            o['status']=Status.CANCELLED.value
        return dict(o)

    async def order_status(self,order_id): return dict(self.orders[order_id])
    async def fills(self,order_id):
        if order_id not in self.orders: raise KeyError(order_id)
        return []
