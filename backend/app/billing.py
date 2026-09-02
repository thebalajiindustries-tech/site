"""Pay-as-you-go metering: measure the tokens each request spends, convert to ₹
(your cost × FX × markup), so the API layer can debit the company's wallet.
"""
import threading

from .config import get_settings

settings = get_settings()

# USD per 1,000,000 tokens: (input, output)
_PRICES = {
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5": (5.0, 25.0),
}
_DEFAULT_PRICE = (3.0, 15.0)

_local = threading.local()


def reset_usage() -> None:
    _local.events = []


def add_usage(model: str, in_tok=0, out_tok=0, cache_read=0, cache_write=0) -> None:
    ev = getattr(_local, "events", None)
    if ev is None:
        ev = []
        _local.events = ev
    ev.append((model, in_tok or 0, out_tok or 0, cache_read or 0, cache_write or 0))


def _usd(model, i, o, cr, cw) -> float:
    pin, pout = _PRICES.get(model, _DEFAULT_PRICE)
    # cache reads bill ~0.1x input, cache writes ~1.25x input
    return (i * pin + o * pout + cr * pin * 0.1 + cw * pin * 1.25) / 1_000_000.0


def request_cost_inr() -> float:
    total = sum(_usd(*e) for e in getattr(_local, "events", []))
    return round(total * settings.USD_INR * settings.BILLING_MARKUP, 4)
