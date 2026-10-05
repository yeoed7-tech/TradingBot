"""Exact Decimal ORM transport: text on SQLite, NUMERIC(65,24) on PostgreSQL."""
from decimal import Decimal
from sqlalchemy import Numeric,String
from sqlalchemy.types import TypeDecorator
from trading_bot.core.portfolio.precision import dec

class ExactDecimal(TypeDecorator):
    impl=Numeric(65,24,asdecimal=True)
    cache_ok=True

    def load_dialect_impl(self,dialect):
        if dialect.name=='sqlite':return dialect.type_descriptor(String(100))
        return dialect.type_descriptor(Numeric(65,24,asdecimal=True))

    def process_bind_param(self,value,dialect):
        if value is None:return None
        value=dec(value)
        return str(value) if dialect.name=='sqlite' else value

    def process_result_value(self,value,dialect):
        return None if value is None else dec(value)
