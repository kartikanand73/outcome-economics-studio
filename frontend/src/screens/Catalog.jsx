import React, { useMemo, useState } from "react";
import { Card, EvidenceBadge, Toggle } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { loadCatalog, money, useCatalog } from "../lib/catalog.js";

const BLANK = {
  provider: "", name: "", tier: "lightweight", input_price_per_m: "", output_price_per_m: "",
  cached_input_price_per_m: null, reasoning_price_per_m: null, separately_metered_reasoning: false,
  context_window: null, source_url: "", as_of: new Date().toISOString().slice(0, 10), evidence: "assumption", notes: "",
};

const today = () => new Date().toISOString().slice(0, 10);

function Num({ label, value, onChange, optional, placeholder, unit = "$/1M" }) {
  return (
    <label className="field">
      <span className="field-label"><span>{label}</span></span>
      <span className="input-wrap">
        <input type="number" step="any" min="0" value={value ?? ""} placeholder={placeholder || (optional ? "Not set" : "0")}
          onChange={(e) => onChange(e.target.value === "" ? (optional ? null : "") : e.target.value)} />
        <span className="unit">{unit}</span>
      </span>
    </label>
  );
}

function Text({ label, value, onChange, placeholder, type = "text" }) {
  return (
    <label className="field">
      <span className="field-label"><span>{label}</span></span>
      <input type={type} value={value ?? ""} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function ModelForm({ initial, isNew, onSave, onCancel }) {
  const [m, setM] = useState(() => ({ ...initial, change_note: "" }));
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => setM((x) => ({ ...x, [k]: v }));
  const pricesChanged = !isNew && ["input_price_per_m", "output_price_per_m", "cached_input_price_per_m", "reasoning_price_per_m"]
    .some((f) => String(m[f] ?? "") !== String(initial[f] ?? ""));
  const save = async () => {
    if (!m.provider.trim() || !m.name.trim()) return setErr("Enter a provider and a model name.");
    if (m.input_price_per_m === "" || m.output_price_per_m === "") return setErr("Enter input and output prices per 1M tokens.");
    setBusy(true); setErr("");
    try {
      const body = { ...m, as_of: pricesChanged && m.as_of === initial.as_of ? today() : m.as_of };
      await onSave(body);
    } catch (e) { setErr(e.message); setBusy(false); }
  };
  return (
    <div className="cat-form">
      <div className="fields">
        <Text label="Provider" value={m.provider} onChange={set("provider")} placeholder="e.g. Azure OpenAI" />
        <Text label="Model name" value={m.name} onChange={set("name")} placeholder="e.g. GPT-6.1 Sol (PTU)" />
        <label className="field">
          <span className="field-label"><span>Tier</span></span>
          <select value={m.tier} onChange={(e) => set("tier")(e.target.value)}>
            <option value="lightweight">Lightweight (first-pass / cheap)</option>
            <option value="larger">Larger (escalation / second opinion)</option>
          </select>
        </label>
        <label className="field">
          <span className="field-label"><span>Price evidence</span></span>
          <select value={m.evidence} onChange={(e) => set("evidence")(e.target.value)}>
            <option value="provider_reported">Provider-reported (published price)</option>
            <option value="measured">Measured (from your bills)</option>
            <option value="assumption">User assumption</option>
          </select>
        </label>
      </div>
      <div className="fields" style={{ marginTop: 10 }}>
        <Num label="Input" value={m.input_price_per_m} onChange={set("input_price_per_m")} />
        <Num label="Cached input" optional placeholder="= input" value={m.cached_input_price_per_m} onChange={set("cached_input_price_per_m")} />
        <Num label="Output" value={m.output_price_per_m} onChange={set("output_price_per_m")} />
        <Num label="Reasoning" optional placeholder="= output" value={m.reasoning_price_per_m} onChange={set("reasoning_price_per_m")} />
        <Num label="Context window" optional unit="tokens" value={m.context_window} onChange={(v) => set("context_window")(v === null ? null : parseInt(v, 10))} />
        <Text label="Prices as of" type="date" value={m.as_of} onChange={set("as_of")} />
      </div>
      <div className="row" style={{ margin: "10px 0" }}>
        <Toggle label="Bills reasoning / thinking tokens (at the reasoning price, or output price if blank)"
          value={m.separately_metered_reasoning} onChange={set("separately_metered_reasoning")} />
      </div>
      <div className="fields wide">
        <Text label="Source link" value={m.source_url} onChange={set("source_url")} placeholder="https://… pricing page or contract" />
        <Text label="Notes" value={m.notes} onChange={set("notes")} placeholder="Tier, region, discount, long-context price…" />
        {pricesChanged && <Text label="Reason for the price change (kept in history)" value={m.change_note} onChange={set("change_note")} placeholder="e.g. EA discount, provider price cut" />}
      </div>
      {err && <div className="issue error"><span className="tag">Error</span><span>{err}</span></div>}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn primary" disabled={busy} onClick={save}>{isNew ? "Add to catalog" : "Save changes"}</button>
        <button className="btn ghost" onClick={onCancel}>Cancel</button>
        {pricesChanged && <span className="small muted">The old price will be kept in this model's history.</span>}
      </div>
    </div>
  );
}

export default function Catalog({ toast }) {
  const list = useCatalog();
  const [query, setQuery] = useState("");
  const [tier, setTier] = useState("all");
  const [editing, setEditing] = useState(null); // catalog id, or "new"
  const [openHistory, setOpenHistory] = useState(null);

  const refresh = () => loadCatalog(true);
  const shown = useMemo(() => list.filter((m) =>
    (tier === "all" || m.tier === tier) &&
    `${m.provider} ${m.name} ${m.notes}`.toLowerCase().includes(query.trim().toLowerCase())), [list, query, tier]);
  const providers = [...new Set(shown.map((m) => m.provider))];

  const create = async (m) => {
    const saved = await api.catalogCreate(m);
    await refresh(); setEditing(null); toast(`Added ${saved.name} to the catalog.`);
  };
  const save = async (m) => {
    const saved = await api.catalogUpdate(m.id, m);
    await refresh(); setEditing(null); toast(`Saved ${saved.name}.`);
  };
  const remove = async (m) => {
    if (!window.confirm(`Remove ${m.provider} ${m.name} from the catalog? Scenarios that already use it keep their copied prices.`)) return;
    await api.catalogDelete(m.id); await refresh(); toast(`Removed ${m.name}.`);
  };
  const restoreOne = async (m) => { await api.catalogRestore(m.id); await refresh(); toast(`Restored the published price for ${m.name}.`); };
  const restoreAll = async () => {
    if (!window.confirm("Restore every shipped model to its published price? Models you added are kept; price changes go into history.")) return;
    await api.catalogRestore(); await refresh(); toast("Published prices restored.");
  };

  return (
    <>
      <Card title="Model catalog"
        subtitle="Shared across all scenarios. Pick these models in Decision routes or Models. Shipped prices are published list prices (standard tier, USD per 1M tokens) with a source link and date; edit them for your contract price and add models as they launch."
        actions={<div className="row">
          <button className="btn primary" onClick={() => setEditing("new")}>+ Add model</button>
          <button className="btn" onClick={restoreAll}>Restore published prices</button>
        </div>}>
        <div className="row">
          <input className="btn" style={{ minWidth: 220, textAlign: "left" }} placeholder="Search provider or model"
            value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search the catalog" />
          <select className="btn" value={tier} onChange={(e) => setTier(e.target.value)} aria-label="Filter by tier">
            <option value="all">All tiers</option>
            <option value="lightweight">Lightweight</option>
            <option value="larger">Larger</option>
          </select>
          <span className="small muted">{shown.length} of {list.length} models · reasoning tokens bill at the output price unless a reasoning price is set</span>
        </div>
        {editing === "new" && <div style={{ marginTop: 12 }}><ModelForm initial={BLANK} isNew onSave={create} onCancel={() => setEditing(null)} /></div>}
      </Card>

      <Card>
        <div style={{ overflowX: "auto" }}>
          <table className="data cat-table">
            <thead>
              <tr><th>Model</th><th>Tier</th><th className="n">Input</th><th className="n">Cached input</th><th className="n">Output</th>
                <th className="n">Reasoning</th><th>As of</th><th>Evidence</th><th /></tr>
            </thead>
            <tbody>
              {providers.map((prov) => (
                <React.Fragment key={prov}>
                  <tr className="provider-row"><td colSpan={9}>{prov}</td></tr>
                  {shown.filter((m) => m.provider === prov).map((m) => (
                    <React.Fragment key={m.id}>
                      <tr className={editing === m.id ? "editing" : ""}>
                        <td>
                          <b>{m.name}</b>
                          <div className="row" style={{ gap: 6, marginTop: 2 }}>
                            {!m.is_seed && <span className="pill mine">Added by you</span>}
                            {m.edited && <span className="pill edited">Price edited</span>}
                            {m.source_url && <a className="small" href={m.source_url} target="_blank" rel="noreferrer">source</a>}
                          </div>
                          {m.notes && <div className="small muted" style={{ maxWidth: 360 }}>{m.notes}</div>}
                        </td>
                        <td><span className={`pill ${m.tier === "larger" ? "larger" : ""}`}>{m.tier}</span></td>
                        <td className="n">{money(m.input_price_per_m)}</td>
                        <td className="n">{m.cached_input_price_per_m != null ? money(m.cached_input_price_per_m) : <span className="muted">= input</span>}</td>
                        <td className="n">{money(m.output_price_per_m)}</td>
                        <td className="n">{!m.separately_metered_reasoning ? <span className="muted">not billed</span>
                          : m.reasoning_price_per_m != null ? money(m.reasoning_price_per_m) : <span className="muted">= output</span>}</td>
                        <td className="small" style={{ whiteSpace: "nowrap" }}>{m.as_of || "—"}</td>
                        <td><EvidenceBadge value={m.evidence} /></td>
                        <td>
                          <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                            <button className="btn small" onClick={() => setEditing(editing === m.id ? null : m.id)}>{editing === m.id ? "Close" : "Edit"}</button>
                            {m.history?.length > 0 && <button className="btn small ghost" onClick={() => setOpenHistory(openHistory === m.id ? null : m.id)}>History ({m.history.length})</button>}
                            {m.is_seed && m.edited && <button className="btn small ghost" onClick={() => restoreOne(m)}>Restore</button>}
                            <button className="btn small ghost danger" onClick={() => remove(m)}>Remove</button>
                          </div>
                        </td>
                      </tr>
                      {editing === m.id && (
                        <tr className="editing"><td colSpan={9}><ModelForm initial={m} onSave={save} onCancel={() => setEditing(null)} /></td></tr>
                      )}
                      {openHistory === m.id && (
                        <tr><td colSpan={9}>
                          <b className="small">Earlier prices (newest last)</b>
                          <ul className="history">
                            {m.history.map((h, i) => (
                              <li key={i}>
                                {money(h.input_price_per_m)} in / {money(h.output_price_per_m)} out
                                {h.cached_input_price_per_m != null ? ` / ${money(h.cached_input_price_per_m)} cached` : ""}
                                {h.as_of ? ` · priced as of ${h.as_of}` : ""} · replaced {h.changed_at.slice(0, 10)}{h.note ? ` · ${h.note}` : ""}
                              </li>
                            ))}
                          </ul>
                        </td></tr>
                      )}
                    </React.Fragment>
                  ))}
                </React.Fragment>
              ))}
              {shown.length === 0 && <tr><td colSpan={9} className="muted">No models match. Clear the search or add a model.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
      <p className="small muted">
        Scenarios copy a model's price when you add it, so saved results stay reproducible. When you change a price here,
        each scenario's Models screen shows “Catalog price differs” with a one-click update.
      </p>
    </>
  );
}
