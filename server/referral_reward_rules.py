"""Integer-only rules; deliberately has no wallet or payment side effects.

This module is not an authorization boundary. Payment settlement must prove
authenticity and lock the referral before applying the returned amounts.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class Rules:
    first_bps: int = 1000
    repeat_bps: int = 500
    points_per_yuan: int = 10
    cap: int = 100
    window_hours: int = 90 * 24
    version: str = 'recharge-v1'

    def __post_init__(self):
        for name in ('first_bps', 'repeat_bps', 'points_per_yuan', 'cap', 'window_hours'):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError('Rules require nonnegative integers')
        if self.first_bps > 10000 or self.repeat_bps > 10000:
            raise ValueError('Reward rate exceeds payment')


def amount_cents(value: str) -> int:
    """Reject floats and sub-cent precision instead of silently rounding money."""
    if not isinstance(value, str):
        raise ValueError('Money must be a decimal string')
    try:
        number = Decimal(value)
        if not number.is_finite() or number < 0 or number * 100 != (number * 100).to_integral_value():
            raise ValueError('Invalid monetary precision')
        return int(number * 100)
    except InvalidOperation as exc:
        raise ValueError('Invalid money') from exc


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError('An explicit timezone is required')
    return value.astimezone(timezone.utc)


def reward(*, cents: int, first_payment: datetime, paid_at: datetime,
           effective_at: datetime, is_first: bool, lifetime_granted: int,
           rules: Rules = Rules()) -> tuple[str, int, int]:
    for value in (cents, lifetime_granted):
        if type(value) is not int or value < 0:
            raise ValueError('Amounts must be nonnegative integers')
    first, paid, effective = map(utc, (first_payment, paid_at, effective_at))
    if paid < effective or paid < first:
        return 'ineligible', 0, 0
    if not is_first and paid >= first + timedelta(hours=rules.window_hours):
        return 'expired', 0, 0
    if is_first and paid != first:
        raise ValueError('First payment does not match historical first payment')
    rate = rules.first_bps if is_first else rules.repeat_bps
    theoretical = cents * rules.points_per_yuan * rate // 1_000_000
    # Gross historical grants consume the cap permanently, including reversed
    # grants. Refund/recharge cycles must not reopen the reward allowance.
    granted = min(theoretical, max(0, rules.cap - lifetime_granted))
    return 'first' if is_first else 'repeat', theoretical, granted


def reversal(*, paid_cents: int, refunded_cents: int, original_grant: int,
             rate_bps: int, points_per_yuan: int, already_reversed: int) -> int:
    values = (paid_cents, refunded_cents, original_grant, rate_bps,
              points_per_yuan, already_reversed)
    if any(type(v) is not int or v < 0 for v in values) or refunded_cents > paid_cents:
        raise ValueError('Invalid refund accounting')
    retained = min(original_grant,
                   (paid_cents - refunded_cents) * points_per_yuan * rate_bps // 1_000_000)
    due = original_grant - retained
    return max(0, due - already_reversed)
