import { useEffect, useState } from "react";
import { api } from "./api.js";

// One shared copy of the model catalog for every screen; refreshed after any catalog edit.
let cache = null;
let inflight = null;
const listeners = new Set();

export function loadCatalog(force = false) {
  if (cache && !force) return Promise.resolve(cache);
  if (inflight && !force) return inflight;
  inflight = api.catalogList().then((list) => {
    cache = list;
    inflight = null;
    listeners.forEach((fn) => fn(list));
    return list;
  }).catch((e) => { inflight = null; throw e; });
  return inflight;
}

export function useCatalog() {
  const [list, setList] = useState(cache || []);
  useEffect(() => {
    listeners.add(setList);
    loadCatalog().then(setList).catch(() => {});
    return () => listeners.delete(setList);
  }, []);
  return list;
}

export const PRICE_FIELDS = ["input_price_per_m", "output_price_per_m", "cached_input_price_per_m", "reasoning_price_per_m"];

export function money(v) {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  const d = n !== 0 && Math.abs(n) < 0.1 ? 3 : 2;
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: Math.max(d, 2) })}`;
}

export function priceLabel(m) {
  return `${money(m.input_price_per_m)} in / ${money(m.output_price_per_m)} out per 1M`;
}

const same = (a, b) => (a === null || a === undefined || a === "" ? null : Number(a)) === (b === null || b === undefined || b === "" ? null : Number(b));

// Has the catalog moved on since this scenario model copied its prices?
export function catalogDiff(model, entry) {
  if (!entry) return null;
  const changed = PRICE_FIELDS.filter((f) => !same(model[f], entry[f]));
  return changed.length ? changed : null;
}

// Prices from the catalog onto a scenario model (usage, latency and limits are left alone).
export function applyCatalogPrices(model, entry) {
  const next = { ...model, catalog_as_of: entry.as_of, evidence: { ...(model.evidence || {}) } };
  PRICE_FIELDS.forEach((f) => { next[f] = entry[f]; next.evidence[f] = entry.evidence; });
  next.separately_metered_reasoning = entry.separately_metered_reasoning;
  return next;
}

// Returns the scenario model id to use for a catalog entry, adding a new model to the scenario if needed.
export async function ensureModelFromCatalog(entry, models, update) {
  const existing = models.find((m) => m.catalog_id === entry.id);
  if (existing) return existing.id;
  const cfg = await api.catalogModelConfig(entry.id);
  let id = cfg.id, n = 2;
  while (models.some((m) => m.id === id)) id = `${cfg.id}-${n++}`;
  cfg.id = id;
  update(["models"], [...models, cfg]);
  return id;
}

export function groupByProvider(list) {
  const groups = new Map();
  list.forEach((m) => {
    if (!groups.has(m.provider)) groups.set(m.provider, []);
    groups.get(m.provider).push(m);
  });
  return [...groups.entries()];
}
