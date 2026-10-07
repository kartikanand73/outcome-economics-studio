"""Latency: fit a lognormal to each route's P50/P95 and compute mixture quantiles.

Latency is not monetary, so floats are fine here. Results are labelled as a
derived approximation. Human-review turnaround is excluded: these are
automated decision latencies.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Z95 = 1.6448536269514722


@dataclass
class RouteLatency:
    share: float
    p50: float
    p95: float


def _cdf(x: float, p50: float, p95: float) -> float:
    if x <= 0:
        return 0.0
    if p50 <= 0:
        return 1.0
    if p95 <= p50:
        return 1.0 if x >= p50 else 0.0
    mu = math.log(p50)
    sigma = (math.log(p95) - mu) / Z95
    return 0.5 * (1 + math.erf((math.log(x) - mu) / (sigma * math.sqrt(2))))


def mixture_quantile(routes: list[RouteLatency], q: float) -> float | None:
    routes = [r for r in routes if r.share > 0]
    total = sum(r.share for r in routes)
    if total <= 0:
        return None
    hi = max(max(r.p95, r.p50) for r in routes) * 20 + 1
    lo = 0.0

    def F(x: float) -> float:
        return sum(r.share * _cdf(x, r.p50, r.p95) for r in routes) / total

    for _ in range(200):
        mid = (lo + hi) / 2
        if F(mid) < q:
            lo = mid
        else:
            hi = mid
    return hi
