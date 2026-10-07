// Immutable nested updates for the scenario draft.
export function getIn(obj, path) {
  return path.reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

export function setIn(obj, path, value) {
  if (path.length === 0) return value;
  const [k, ...rest] = path;
  const clone = Array.isArray(obj) ? [...obj] : { ...(obj || {}) };
  clone[k] = setIn(obj == null ? undefined : obj[k], rest, value);
  return clone;
}

export function uid(prefix = "r") {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

// Which models the Decision routes actually use: id -> { reachable, routes: [names] }.
export function modelUsage(draft) {
  const use = {};
  (draft?.routes || []).forEach((r) => {
    const reachable = Number(r.share_pct) > 0;
    (r.stages || []).forEach((s) => {
      [s.model_id, s.subagents_enabled ? s.subagent_model_id || s.model_id : null].filter(Boolean).forEach((id) => {
        use[id] = use[id] || { reachable: false, routes: [] };
        use[id].reachable = use[id].reachable || reachable;
        if (!use[id].routes.includes(r.name)) use[id].routes.push(r.name);
      });
    });
  });
  return use;
}

// What the routes need from the Human, tool & infra screen.
export function routeNeeds(draft) {
  const routes = draft?.routes || [];
  return {
    humanReview: routes.some((r) => r.direct_human || r.human_review_mandatory || Number(r.human_review_pct) > 0),
    tools: routes.some((r) => Number(r.rule_tool_calls) > 0 || (r.stages || []).some((s) => s.tools_exposed)),
    llm: routes.some((r) => (r.stages || []).length > 0),
  };
}
