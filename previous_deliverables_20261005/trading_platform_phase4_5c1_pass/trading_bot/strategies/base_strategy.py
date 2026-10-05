from abc import ABC, abstractmethod
from collections.abc import Mapping
from trading_bot.core.events.models import Bar, Signal

class Strategy(ABC):
    """Receives only completed bars. Owns indicators, NEVER cash, quantity or APIs.

    Return targets each bar to maintain allocation, or None to hold current units.
    A fresh instance is required for every independent backtest/fold.
    """
    def snapshot_state(self):
        """Return JSON-safe indicator state, or None for deterministic full replay."""
        return None

    def restore_state(self,state):
        raise NotImplementedError('strategy does not support state snapshots')

    @abstractmethod
    def on_data(self, bars: Mapping[str, Bar], portfolio=None) -> list[Signal]: ...

REGISTRY: dict[str, type[Strategy]] = {}

def register(name):
    def decorate(cls):
        if name in REGISTRY:
            raise ValueError(f'duplicate strategy: {name}')
        REGISTRY[name] = cls
        return cls
    return decorate

def create_strategy(name, params=None):
    if ':' in name:
        from importlib import import_module
        module, class_name = name.split(':', 1)
        cls = getattr(import_module(module), class_name)
    else:
        if name not in REGISTRY:
            raise ValueError(f'unknown strategy {name}; available: {list(REGISTRY)}')
        cls = REGISTRY[name]
    strategy = cls(**(params or {}))
    if not isinstance(strategy, Strategy):
        raise TypeError('plugin must inherit Strategy')
    return strategy
