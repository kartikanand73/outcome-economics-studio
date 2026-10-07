"""Monetary helpers. All intermediate math stays at full Decimal precision;
rounding happens only at presentation time."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, getcontext

getcontext().prec = 34

MILLION = Decimal(1_000_000)
HUNDRED = Decimal(100)
ZERO = Decimal(0)

# ISO 4217 minor units for currencies we expect; unknown currencies default to 2.
MINOR_UNITS = {"USD": 2, "EUR": 2, "GBP": 2, "INR": 2, "CAD": 2, "AUD": 2, "CHF": 2,
               "SGD": 2, "JPY": 0, "KRW": 0, "BHD": 3, "KWD": 3}

UNIT_COST_PLACES = 6  # per-task and per-call costs are often sub-cent


def pct(x: Decimal | None) -> Decimal:
    return (x or ZERO) / HUNDRED


def D(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(str(x))
    return Decimal(x)


def minor_units(currency: str) -> int:
    return MINOR_UNITS.get((currency or "USD").upper(), 2)


def round_money(value: Decimal, currency: str = "USD") -> Decimal:
    """Round an aggregate amount (daily/monthly/annual) to the currency's minor unit."""
    q = Decimal(1).scaleb(-minor_units(currency))
    return value.quantize(q, rounding=ROUND_HALF_UP)


def round_unit(value: Decimal, places: int = UNIT_COST_PLACES) -> Decimal:
    """Round a unit cost (per task / per call) for display without losing sub-cent detail."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def safe_div(a: Decimal, b: Decimal) -> Decimal | None:
    return None if b == 0 else a / b
