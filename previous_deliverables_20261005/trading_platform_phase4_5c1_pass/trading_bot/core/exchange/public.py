"""Segregated ports: paper only uses PublicMarketData, never AccountAccess."""
from typing import Protocol
from trading_bot.core.events.market import Quote
from trading_bot.core.events.models import Bar

class PublicMarketData(Protocol):
    async def ticker(self,symbol: str) -> dict: ...
    async def candles(self,symbol: str,timeframe: str,since_ms: int,until_ms: int) -> list[Bar]: ...
    async def order_book(self,symbol: str) -> Quote: ...
    async def market_metadata(self,symbol: str) -> dict: ...
    async def fees(self,symbol: str) -> dict: ...
    async def close(self) -> None: ...

class AccountAccessUnavailable(RuntimeError): pass

class UnavailableAccountAccess:
    """Explicit unsupported account contract, not fake balances or orders.

    This is NOT attached to the public adapter and never injected into paper.
    """
    async def balances(self): raise AccountAccessUnavailable('authenticated account access not implemented in Phase 3')
    async def positions(self): raise AccountAccessUnavailable('authenticated account access not implemented in Phase 3')
    async def orders(self): raise AccountAccessUnavailable('authenticated account access not implemented in Phase 3')
    async def order_status(self,order_id): raise AccountAccessUnavailable('authenticated account access not implemented in Phase 3')
    async def fills(self,order_id): raise AccountAccessUnavailable('authenticated account access not implemented in Phase 3')
