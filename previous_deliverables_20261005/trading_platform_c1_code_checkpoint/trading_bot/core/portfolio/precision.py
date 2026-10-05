"""Exact accounting boundary. Market rules round at order entry, not here."""
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_DOWN, ROUND_CEILING, ROUND_FLOOR, localcontext, getcontext

# 24 fractional digits survive partial cost allocation and fit NUMERIC(65,24).
LEDGER_UNIT=Decimal('0.000000000000000000000001')

def dec(value):
    # 65 significant digits are required for large KRW cash plus 24-place fees.
    # Decimal contexts are local to the executing thread/task; establish the
    # accounting context whenever external data crosses into the ledger.
    if getcontext().prec<65:getcontext().prec=65
    result=Decimal(str(value))
    if not result.is_finite():raise ValueError('nonfinite numeric value')
    return result

def ledger(value):
    with localcontext() as ctx:
        ctx.prec=65
        return dec(value).quantize(LEDGER_UNIT,rounding=ROUND_HALF_EVEN)

def floor_step(value,step):
    value,step=dec(value),dec(step)
    if step<=0:raise ValueError('invalid quantity step')
    return max(Decimal(0),(value/step).to_integral_value(rounding=ROUND_DOWN)*step)

def tick_price(value,tick,up):
    value,tick=dec(value),dec(tick)
    if tick<=0:raise ValueError('invalid price tick')
    return (value/tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*tick

# Legacy display helpers retained for old diagnostics; never used by the ledger.
def money(value):return dec(value).quantize(Decimal('0.00000001'),rounding=ROUND_HALF_EVEN)
def quantity(value):return dec(value).quantize(Decimal('0.00000001'),rounding=ROUND_HALF_EVEN)
