// Formatting for the backend's metric envelopes:
// { value, rounded, kind, evidence, note, unbounded, reasons }
const SYMBOLS = { USD: "$", EUR: "€", GBP: "£", INR: "₹", JPY: "¥" };

export const EVIDENCE = {
  assumption: "User assumption",
  measured: "Measured",
  provider_reported: "Provider-reported",
  derived: "Derived",
};

export const CATEGORY_LABELS = {
  lightweight_model: "Lightweight model",
  larger_model: "Larger model",
  human_review: "Human review",
  tool_api: "Tool / API",
  evaluation: "Evaluation / governance",
  other_variable: "Other variable",
  infrastructure: "Infrastructure (allocated)",
};

export function sym(cur) {
  return SYMBOLS[cur] ?? `${cur} `;
}

export function num(v, digits = 2) {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (!isFinite(n)) return String(v);
  return n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: digits });
}

export function fmtValue(v, kind, cur = "USD") {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  const s = sym(cur);
  switch (kind) {
    case "money":
      return `${s}${n.toLocaleString(undefined, { minimumFractionDigits: cur === "JPY" ? 0 : 2, maximumFractionDigits: cur === "JPY" ? 0 : 2 })}`;
    case "unit_money": {
      const a = Math.abs(n);
      const d = a === 0 ? 2 : a < 0.01 ? 6 : a < 1 ? 4 : 2;
      return `${s}${n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })}`;
    }
    case "pct":
      return `${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
    case "tokens":
    case "count_int":
      return Math.round(n).toLocaleString();
    case "ms":
      return `${Math.round(n).toLocaleString()} ms`;
    default:
      return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
}

export function fmt(m, cur = "USD", { emptyLabel = "Not measured" } = {}) {
  if (!m) return "—";
  if (m.unbounded) return "Unbounded";
  const v = m.rounded ?? m.value;
  if (v === null || v === undefined) return emptyLabel;
  return fmtValue(v, m.kind, cur);
}

export function compact(v, cur) {
  const n = Number(v);
  const s = cur ? sym(cur) : "";
  const a = Math.abs(n);
  if (a >= 1e6) return `${s}${(n / 1e6).toFixed(1)}M`;
  if (a >= 1e4) return `${s}${(n / 1e3).toFixed(1)}K`;
  if (a >= 1) return `${s}${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  if (a === 0) return `${s}0`;
  return `${s}${n.toPrecision(2)}`;
}
