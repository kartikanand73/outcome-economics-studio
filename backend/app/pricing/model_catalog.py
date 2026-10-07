"""Shared, editable model price catalog.

* Seeded from ``seed_catalog.json`` (published list prices with source URL and as-of date).
* Stored in SQLite next to the scenarios, so your edits and additions survive restarts.
* Seeding never overwrites an entry you edited; "restore" puts a seed entry back to its published price.
* Every price change is kept in the entry's ``history``.
* Scenarios copy a catalog entry's prices into their own model (``catalog_id`` links back), so a saved
  scenario stays reproducible; the UI offers "use catalog prices" when the catalog has moved on.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.domain.models import (BoundsMode, CallLimits, CatalogModel, ContextBounds, Evidence, ModelConfig, PriceChange, Tier)
from app.pricing.catalog import PriceProvider, PriceQuote

SEED_PATH = Path(__file__).with_name("seed_catalog.json")
PRICE_FIELDS = ("input_price_per_m", "output_price_per_m", "cached_input_price_per_m", "reasoning_price_per_m")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(provider: str, name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", f"{provider} {name}".lower()).strip("-") or "model"


def load_seed() -> list[CatalogModel]:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    out = []
    for m in data["models"]:
        entry = CatalogModel(**m)
        entry.is_seed = True
        out.append(entry)
    return out


class CatalogStore:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("CREATE TABLE IF NOT EXISTS model_catalog (id TEXT PRIMARY KEY, doc TEXT NOT NULL)")
        self._conn.commit()

    # ---------------------------------------------------------------- read
    def list(self) -> list[CatalogModel]:
        rows = self._conn.execute("SELECT doc FROM model_catalog").fetchall()
        items = [CatalogModel.model_validate_json(r["doc"]) for r in rows]
        return sorted(items, key=lambda m: (m.provider.lower() == "custom", m.provider.lower(),
                                            m.tier != Tier.LARGER, m.name.lower()))

    def get(self, mid: str) -> CatalogModel | None:
        r = self._conn.execute("SELECT doc FROM model_catalog WHERE id = ?", (mid,)).fetchone()
        return CatalogModel.model_validate_json(r["doc"]) if r else None

    # ---------------------------------------------------------------- write
    def _put(self, m: CatalogModel) -> CatalogModel:
        self._conn.execute("INSERT OR REPLACE INTO model_catalog (id, doc) VALUES (?, ?)", (m.id, m.model_dump_json()))
        self._conn.commit()
        return m

    def seed(self) -> int:
        """Insert published entries that are missing. Never touches existing entries."""
        added = 0
        for s in load_seed():
            if self.get(s.id) is None:
                s.updated_at = _now()
                self._put(s)
                added += 1
        return added

    def create(self, m: CatalogModel) -> CatalogModel:
        m = m.model_copy(deep=True)
        base = m.id or slugify(m.provider, m.name)
        mid, n = base, 2
        while self.get(mid) is not None:
            mid, n = f"{base}-{n}", n + 1
        m.id, m.is_seed, m.edited, m.history = mid, False, False, []
        if not m.as_of:
            m.as_of = datetime.now(timezone.utc).date().isoformat()
        m.updated_at = _now()
        return self._put(m)

    def update(self, mid: str, m: CatalogModel, note: str = "") -> CatalogModel:
        old = self.get(mid)
        if old is None:
            raise KeyError(mid)
        new = m.model_copy(deep=True)
        new.id, new.is_seed, new.history = mid, old.is_seed, list(old.history)
        if old.price_tuple() != new.price_tuple():
            new.history.append(PriceChange(changed_at=_now(), as_of=old.as_of, note=note,
                                           **{f: getattr(old, f) for f in PRICE_FIELDS}))
            if not new.as_of or new.as_of == old.as_of:
                new.as_of = datetime.now(timezone.utc).date().isoformat()
        new.edited = old.edited or (old.is_seed and old.price_tuple() != new.price_tuple())
        new.updated_at = _now()
        return self._put(new)

    def delete(self, mid: str) -> bool:
        cur = self._conn.execute("DELETE FROM model_catalog WHERE id = ?", (mid,))
        self._conn.commit()
        return cur.rowcount > 0

    def restore(self, mid: str | None = None) -> list[CatalogModel]:
        """Put seed entries back to their published values (one, or all). Your own models are untouched."""
        seeds = {s.id: s for s in load_seed()}
        targets = [mid] if mid else list(seeds)
        for sid in targets:
            if sid not in seeds:
                raise KeyError(sid)
            pub = seeds[sid]
            cur = self.get(sid)
            if cur is not None and cur.price_tuple() != pub.price_tuple():
                pub.history = list(cur.history) + [PriceChange(
                    changed_at=_now(), as_of=cur.as_of, note="restored published price",
                    **{f: getattr(cur, f) for f in PRICE_FIELDS})]
            elif cur is not None:
                pub.history = list(cur.history)
            pub.updated_at = _now()
            self._put(pub)
        return self.list()


# ------------------------------------------------------------------ scenario model from catalog
TIER_DEFAULTS = {
    Tier.LIGHTWEIGHT: dict(avg_input_tokens=Decimal(650), avg_output_tokens=Decimal(40), avg_reasoning_tokens=Decimal(0),
                           p50=Decimal(250), p95=Decimal(700), system=Decimal(300), user=Decimal(350),
                           user_max=Decimal(500), max_out=Decimal(128), max_reasoning=Decimal(256), retries=1),
    Tier.LARGER: dict(avg_input_tokens=Decimal(1000), avg_output_tokens=Decimal(60), avg_reasoning_tokens=Decimal(120),
                      p50=Decimal(2500), p95=Decimal(5500), system=Decimal(450), user=Decimal(350),
                      user_max=Decimal(500), max_out=Decimal(256), max_reasoning=Decimal(1024), retries=2),
}


def to_model_config(entry: CatalogModel, model_id: str | None = None) -> ModelConfig:
    """A scenario model with the catalog's prices and bounded, tier-based usage defaults.

    Prices carry the catalog entry's evidence label; usage, latency and limits are user assumptions.
    """
    d = TIER_DEFAULTS[entry.tier]
    price_ev = entry.evidence
    return ModelConfig(
        id=model_id or entry.id, provider=entry.provider, name=entry.name, tier=entry.tier,
        input_price_per_m=entry.input_price_per_m, output_price_per_m=entry.output_price_per_m,
        cached_input_price_per_m=entry.cached_input_price_per_m, reasoning_price_per_m=entry.reasoning_price_per_m,
        separately_metered_reasoning=entry.separately_metered_reasoning,
        avg_input_tokens=d["avg_input_tokens"], avg_output_tokens=d["avg_output_tokens"],
        avg_reasoning_tokens=d["avg_reasoning_tokens"] if entry.separately_metered_reasoning else Decimal(0),
        avg_calls_per_task=Decimal(1), retry_rate_pct=Decimal(1), retries_enabled=True,
        p50_latency_ms=d["p50"], p95_latency_ms=d["p95"],
        context=ContextBounds(system_prompt_tokens=d["system"], avg_user_input_tokens=d["user"],
                              max_user_input_tokens=d["user_max"], max_output_tokens=d["max_out"],
                              max_reasoning_tokens=d["max_reasoning"] if entry.separately_metered_reasoning else None),
        limits=CallLimits(max_model_calls=1, max_retries=d["retries"]),
        bounds_mode=BoundsMode.DEFAULT,
        catalog_id=entry.id, catalog_as_of=entry.as_of,
        evidence={f: price_ev for f in PRICE_FIELDS},
    )


class CatalogPriceProvider(PriceProvider):
    """PriceProvider backed by the editable catalog."""

    name = "catalog"

    def __init__(self, store: CatalogStore):
        self.store = store

    def list_models(self) -> list[ModelConfig]:
        return [to_model_config(e) for e in self.store.list()]

    def quote(self, model_id: str) -> PriceQuote | None:
        e = self.store.get(model_id)
        if e is None:
            return None
        return PriceQuote(e.provider, e.name, e.input_price_per_m, e.output_price_per_m,
                          e.cached_input_price_per_m, e.reasoning_price_per_m, e.evidence,
                          e.source_url or "Model catalog", e.as_of)
