import React from "react";
import { EVIDENCE, fmt } from "../lib/format.js";
import { getIn } from "../lib/state.js";

const CYCLE = ["assumption", "measured", "provider_reported"];

export function EvidenceBadge({ value, onChange, title }) {
  const ev = value || "assumption";
  if (!onChange || ev === "derived") {
    return <span className={`ev ev-${ev}`} title={title}>{EVIDENCE[ev] ?? ev}</span>;
  }
  const next = CYCLE[(CYCLE.indexOf(ev) + 1) % CYCLE.length];
  return (
    <button type="button" className={`ev ev-${ev}`} title={`Evidence label — click to mark as ${EVIDENCE[next]}`}
      onClick={() => onChange(next)}>
      {EVIDENCE[ev] ?? ev}
    </button>
  );
}

// Binding helper: bind(path) -> props for NumField / TextField / Toggle with evidence labels.
export function makeBinder(draft, update) {
  return (path, extra = {}) => {
    const parent = path.slice(0, -1);
    const key = path[path.length - 1];
    return {
      value: getIn(draft, path),
      onChange: (v) => update(path, v),
      ev: getIn(draft, [...parent, "evidence", key]),
      onEv: extra.noEvidence ? undefined : (e) => update([...parent, "evidence", key], e),
      ...extra,
    };
  };
}

export function NumField({ label, value, onChange, unit, optional, ev, onEv, hint, unsetLabel, step = "any",
                           integer, noEvidence }) {
  const empty = value === null || value === undefined;
  return (
    <label className={`field ${optional && empty && /unbounded/i.test(unsetLabel || "") ? "unset" : ""}`}>
      <span className="field-label">
        <span>{label}</span>
        {!noEvidence && onEv && <EvidenceBadge value={ev} onChange={onEv} />}
      </span>
      <span className="input-wrap">
        <input type="number" step={integer ? 1 : step} inputMode="decimal"
          value={empty ? "" : value}
          placeholder={optional ? unsetLabel || "Not set" : "0"}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") onChange(optional ? null : 0);
            else onChange(integer ? parseInt(raw, 10) : raw);
          }} />
        {unit && <span className="unit">{unit}</span>}
      </span>
      {hint && <span className="hint">{hint}</span>}
    </label>
  );
}

export function TextField({ label, value, onChange, placeholder, multiline }) {
  return (
    <label className="field">
      <span className="field-label"><span>{label}</span></span>
      {multiline ? (
        <textarea rows={2} value={value ?? ""} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <input value={value ?? ""} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      )}
    </label>
  );
}

export function SelectField({ label, value, onChange, options }) {
  return (
    <label className="field">
      <span className="field-label"><span>{label}</span></span>
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}

export function Toggle({ label, value, onChange, hint }) {
  return (
    <label className="toggle" title={hint}>
      <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

export function Issues({ issues, filter, empty }) {
  const list = (issues || []).filter(filter || (() => true));
  if (!list.length) return empty ? <p className="muted small">{empty}</p> : null;
  return list.map((i, idx) => (
    <div key={idx} className={`issue ${i.severity}`}>
      <span className="tag">{i.severity}</span>
      <span>{i.message}</span>
    </div>
  ));
}

export function Stat({ label, metric, cur, sub, hero, alert, okFlag, children }) {
  return (
    <div className={`stat ${hero ? "hero" : ""} ${alert ? "alert" : ""} ${okFlag ? "ok-flag" : ""}`}>
      <span className="label">
        <span>{label}</span>
        {metric && <EvidenceBadge value={metric.evidence} title={metric.note} />}
      </span>
      <span className="value">{children ?? fmt(metric, cur)}</span>
      {sub && <span className="sub">{sub}</span>}
    </div>
  );
}

export function Card({ title, subtitle, actions, children }) {
  return (
    <div className="card">
      {(title || actions) && (
        <div className="card-head">
          <div style={{ flex: 1, minWidth: 0 }}>
            {title && <h3>{title}</h3>}
            {subtitle && <p>{subtitle}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </div>
  );
}
