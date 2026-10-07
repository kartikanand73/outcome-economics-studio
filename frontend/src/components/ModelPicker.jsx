import React, { useState } from "react";
import { ensureModelFromCatalog, groupByProvider, priceLabel, useCatalog } from "../lib/catalog.js";

// Pick a model for a stage: models already in this scenario, or any model in the shared catalog.
// Picking a catalog model copies it into the scenario (with its current catalog price) the first time.
export default function ModelPicker({ label = "Model", value, models, update, onPick, allowSame = false }) {
  const catalog = useCatalog();
  const [busy, setBusy] = useState(false);
  const inScenario = new Set(models.map((m) => m.catalog_id).filter(Boolean));
  const current = models.find((m) => m.id === value);

  const choose = async (v) => {
    if (v === "" && allowSame) return onPick(null);
    if (v.startsWith("s:")) return onPick(v.slice(2));
    const entry = catalog.find((c) => c.id === v.slice(2));
    if (!entry) return;
    setBusy(true);
    try { onPick(await ensureModelFromCatalog(entry, models, update)); } finally { setBusy(false); }
  };

  return (
    <label className="field picker">
      <span className="field-label"><span>{label}</span></span>
      <select value={value ? `s:${value}` : ""} disabled={busy} onChange={(e) => choose(e.target.value)}>
        {allowSame && <option value="">Same as stage</option>}
        <optgroup label="In this scenario">
          {models.map((m) => (
            <option key={m.id} value={`s:${m.id}`}>
              {m.name} · {m.tier === "larger" ? "larger" : "lightweight"} · {priceLabel(m)}
            </option>
          ))}
        </optgroup>
        {groupByProvider(catalog.filter((c) => !inScenario.has(c.id))).map(([provider, items]) => (
          <optgroup key={provider} label={`Catalog · ${provider}`}>
            {items.map((c) => (
              <option key={c.id} value={`c:${c.id}`}>
                {c.name} · {c.tier === "larger" ? "larger" : "lightweight"} · {priceLabel(c)}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {current && (
        <span className="hint">
          {current.provider ? `${current.provider} · ` : ""}{priceLabel(current)}
          {current.catalog_as_of ? ` · catalog price as of ${current.catalog_as_of}` : " · price entered by hand"}
        </span>
      )}
    </label>
  );
}
