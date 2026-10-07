import React from "react";
import { Card, EvidenceBadge, NumField, SelectField, TextField, Toggle, makeBinder } from "../components/ui.jsx";
import { applyCatalogPrices, catalogDiff, money, priceLabel, useCatalog } from "../lib/catalog.js";
import { modelUsage } from "../lib/state.js";
import { fmtValue } from "../lib/format.js";

const FIELD_LABEL = { input_price_per_m: "input", output_price_per_m: "output", cached_input_price_per_m: "cached input",
  reasoning_price_per_m: "reasoning" };

function CatalogLink({ m, entry, onApply }) {
  if (!m.catalog_id) {
    return <div className="catalog-link">Price entered by hand · not linked to the model catalog</div>;
  }
  if (!entry) {
    return <div className="catalog-link">Linked to catalog entry “{m.catalog_id}”, which no longer exists. Prices here are kept as they are.</div>;
  }
  const diff = catalogDiff(m, entry);
  if (!diff) {
    return (
      <div className="catalog-link">
        Matches catalog: {entry.provider} {entry.name} · {priceLabel(entry)} · as of {entry.as_of}
        {entry.source_url && <a href={entry.source_url} target="_blank" rel="noreferrer">source</a>}
      </div>
    );
  }
  return (
    <div className="catalog-link stale">
      <span>
        <b>Catalog price differs</b> ({diff.map((f) => FIELD_LABEL[f]).join(", ")}). Catalog now lists {priceLabel(entry)} as of {entry.as_of};
        this scenario uses {money(m.input_price_per_m)} / {money(m.output_price_per_m)}{m.catalog_as_of ? ` from ${m.catalog_as_of}` : ""}.
      </span>
      <button className="btn small" onClick={onApply}>Use catalog prices</button>
    </div>
  );
}

function callCostPreview(m) {
  // display-only preview; the backend engine is authoritative (Decimal)
  const n = (x) => Number(x || 0);
  const cachedPrice = m.cached_input_price_per_m ?? m.input_price_per_m;
  const reasoningPrice = m.reasoning_price_per_m ?? m.output_price_per_m;
  const cached = n(m.avg_input_tokens) * n(m.cached_input_share_pct) / 100;
  return (n(m.avg_input_tokens) * n(m.input_price_per_m) - cached * (n(m.input_price_per_m) - n(cachedPrice))
    + n(m.avg_output_tokens) * n(m.output_price_per_m)
    + (m.separately_metered_reasoning ? n(m.avg_reasoning_tokens) * n(reasoningPrice) : 0)) / 1e6;
}

function ModelCard({ m, idx, draft, update, usage, cur, entry }) {
  const p = ["models", idx];
  const b = makeBinder(draft, update);
  const mp = (k) => [...p, k];
  return (
    <Card title={m.name}
      subtitle={`${m.provider || "—"} · ${m.tier === "larger" ? "Larger model" : "Lightweight model"} · used in ${usage.routes.join(", ")}${usage.reachable ? "" : " (only routes at 0% share, not in results yet)"}`}
      actions={<>
        <span className="small muted">Expected cost / call ≈ <b>{fmtValue(callCostPreview(m), "unit_money", cur)}</b></span>
        <EvidenceBadge value="derived" title="Preview only; results use the Decimal engine" />

      </>}>
      <div className="fields">
        <TextField label="Model name" value={m.name} onChange={(v) => update(mp("name"), v)} />
        <TextField label="Provider" value={m.provider} onChange={(v) => update(mp("provider"), v)} />
        <SelectField label="Tier" value={m.tier} onChange={(v) => update(mp("tier"), v)}
          options={[{ value: "lightweight", label: "Lightweight" }, { value: "larger", label: "Larger" }]} />
      </div>
      <div className="section-title">Pricing per million tokens</div>
      <CatalogLink m={m} entry={entry} onApply={() => update(p, applyCatalogPrices(m, entry))} />
      <div className="fields">
        <NumField label="Input price" unit={`${cur}/M`} {...b(mp("input_price_per_m"))} />
        <NumField label="Output price" unit={`${cur}/M`} {...b(mp("output_price_per_m"))} />
        <NumField label="Cached-input price" unit={`${cur}/M`} optional unsetLabel="= input price" {...b(mp("cached_input_price_per_m"))} />
        <NumField label="Reasoning price" unit={`${cur}/M`} optional unsetLabel="= output price" {...b(mp("reasoning_price_per_m"))} />
      </div>
      <div className="row" style={{ margin: "10px 0 2px", gap: 16 }}>
        <Toggle label="Reasoning tokens are separately metered" value={m.separately_metered_reasoning}
          onChange={(v) => update(mp("separately_metered_reasoning"), v)} />
        <Toggle label="Retries enabled" value={m.retries_enabled} onChange={(v) => update(mp("retries_enabled"), v)} />
      </div>
      <div className="section-title">Expected usage per call</div>
      <div className="fields">
        <NumField label="Avg input tokens" {...b(mp("avg_input_tokens"))} />
        <NumField label="Avg output tokens" {...b(mp("avg_output_tokens"))} />
        <NumField label="Avg reasoning tokens" {...b(mp("avg_reasoning_tokens"))}
          hint={m.separately_metered_reasoning ? "" : "Ignored unless separately metered"} />
        <NumField label="Cached share of input" unit="%" {...b(mp("cached_input_share_pct"))} />
        <NumField label="Avg calls per applicable task" {...b(mp("avg_calls_per_task"))} />
        <NumField label="Retry rate" unit="% of calls" {...b(mp("retry_rate_pct"))} />
        <NumField label="P50 latency" unit="ms" {...b(mp("p50_latency_ms"))} />
        <NumField label="P95 latency" unit="ms" {...b(mp("p95_latency_ms"))} />
      </div>
    </Card>
  );
}

export default function Models({ draft, update, onOpenCatalog, onOpenRoutes }) {
  const catalog = useCatalog();
  const byId = Object.fromEntries(catalog.map((c) => [c.id, c]));
  const usage = modelUsage(draft);
  const used = draft.models.map((m, i) => [m, i]).filter(([m]) => usage[m.id]);
  const unused = draft.models.filter((m) => !usage[m.id]);
  const stale = used.map(([m]) => m).filter((m) => m.catalog_id && byId[m.catalog_id] && catalogDiff(m, byId[m.catalog_id]));
  const updateAll = () => update(["models"], draft.models.map((m) =>
    (usage[m.id] && m.catalog_id && byId[m.catalog_id] && catalogDiff(m, byId[m.catalog_id]) ? applyCatalogPrices(m, byId[m.catalog_id]) : m)));
  const removeUnused = () => update(["models"], draft.models.filter((m) => usage[m.id]));
  return (
    <>
      <Card title="Models used by your decision routes"
        subtitle="Choose models on the Decision routes screen; this screen sets their prices, token usage and latency. Prices were copied from the model catalog when the model was picked."
        actions={<div className="row">
          {onOpenRoutes && <button className="btn" onClick={onOpenRoutes}>Choose models in Decision routes</button>}
          {onOpenCatalog && <button className="btn ghost" onClick={onOpenCatalog}>Edit catalog</button>}
        </div>}>
        {used.length === 0 && (
          <p className="small" style={{ margin: 0 }}>
            No route calls an LLM, so LLM cost is <b>$0</b>. Add a model stage to a route on the Decision routes screen to price one here.
          </p>
        )}
        {stale.length > 0 && (
          <div className="catalog-link stale">
            <span><b>{stale.length} model{stale.length > 1 ? "s" : ""}</b> use older prices than the catalog: {stale.map((m) => m.name).join(", ")}.</span>
            <button className="btn small" onClick={updateAll}>Use catalog prices for all</button>
          </div>
        )}
      </Card>
      {used.map(([m, i]) => (
        <ModelCard key={m.id} m={m} idx={i} draft={draft} update={update} usage={usage[m.id]}
          cur={draft.workload.currency} entry={m.catalog_id ? byId[m.catalog_id] : undefined} />
      ))}
      {unused.length > 0 && (
        <div className="catalog-link" style={{ marginTop: 12 }}>
          <span>{unused.length} model{unused.length > 1 ? "s are" : " is"} saved in this scenario but not used by any route: {unused.map((m) => m.name).join(", ")}.
            They are hidden and don't affect results.</span>
          <button className="btn small" onClick={removeUnused}>Remove {unused.length > 1 ? "them" : "it"}</button>
        </div>
      )}
    </>
  );
}
