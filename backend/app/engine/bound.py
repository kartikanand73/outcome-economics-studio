"""A quantity that is either a finite Decimal or explicitly unbounded.

An unbounded value carries the reasons it is unbounded so the UI can say *why*
a workflow has no maximum instead of printing a fake number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Bound:
    value: Decimal | None
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def bounded(self) -> bool:
        return self.value is not None

    @staticmethod
    def of(v) -> "Bound":
        return Bound(Decimal(v))

    @staticmethod
    def unbounded(reason: str) -> "Bound":
        return Bound(None, (reason,))

    def __add__(self, other: "Bound") -> "Bound":
        if self.bounded and other.bounded:
            return Bound(self.value + other.value)
        return Bound(None, _merge(self.reasons, other.reasons))

    def __mul__(self, other: "Bound") -> "Bound":
        # zero times anything (even unbounded) is zero: an unreachable factor
        if (self.bounded and self.value == 0) or (other.bounded and other.value == 0):
            return Bound(Decimal(0))
        if self.bounded and other.bounded:
            return Bound(self.value * other.value)
        return Bound(None, _merge(self.reasons, other.reasons))

    def min(self, other: "Bound") -> "Bound":
        if self.bounded and other.bounded:
            return self if self.value <= other.value else other
        return self if self.bounded else other if other.bounded else Bound(None, _merge(self.reasons, other.reasons))

    def max(self, other: "Bound") -> "Bound":
        if self.bounded and other.bounded:
            return self if self.value >= other.value else other
        return Bound(None, _merge(self.reasons, other.reasons))


def _merge(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
    out = list(a)
    for r in b:
        if r not in out:
            out.append(r)
    return tuple(out)


def bsum(items) -> Bound:
    total = Bound(Decimal(0))
    for i in items:
        total = total + i
    return total
