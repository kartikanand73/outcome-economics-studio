// Thin fetch wrapper around the FastAPI backend.
async function req(method, url, body, isForm = false) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) opts.body = body;
    else {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
  }
  const res = await fetch(url, opts);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    let msg = data && data.detail ? data.detail : `${res.status} ${res.statusText}`;
    if (Array.isArray(msg)) msg = msg.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

export const api = {
  list: () => req("GET", "/api/scenarios"),
  get: (id) => req("GET", `/api/scenarios/${id}`),
  template: () => req("GET", "/api/scenarios/template"),
  create: (sc) => req("POST", "/api/scenarios", sc),
  update: (id, sc) => req("PUT", `/api/scenarios/${id}`, sc),
  remove: (id) => req("DELETE", `/api/scenarios/${id}`),
  clone: (id, name) => req("POST", `/api/scenarios/${id}/clone`, { name }),
  removeBenchmark: (id) => req("DELETE", `/api/scenarios/${id}/benchmark`),
  resetSamples: () => req("POST", "/api/samples/reset"),
  calculate: (sc) => req("POST", "/api/calculate", sc),
  compare: (ids) => req("POST", "/api/compare", { ids }),
  catalogList: () => req("GET", "/api/catalog"),
  catalogCreate: (m) => req("POST", "/api/catalog", m),
  catalogUpdate: (id, m) => req("PUT", `/api/catalog/${id}`, m),
  catalogDelete: (id) => req("DELETE", `/api/catalog/${id}`),
  catalogRestore: (id) => req("POST", id ? `/api/catalog/${id}/restore` : "/api/catalog/restore"),
  catalogModelConfig: (id) => req("GET", `/api/catalog/${id}/model-config`),
  preview: (file) => {
    const f = new FormData();
    f.append("file", file);
    return req("POST", "/api/import/preview", f, true);
  },
  importInto: (id, file, applyToInputs) => {
    const f = new FormData();
    f.append("file", file);
    f.append("apply_to_inputs", applyToInputs ? "true" : "false");
    return req("POST", `/api/scenarios/${id}/import`, f, true);
  },
  importScenario: (file) => {
    const f = new FormData();
    f.append("file", file);
    return req("POST", "/api/import/scenario", f, true);
  },
};
