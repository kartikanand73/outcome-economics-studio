import { useEffect, useState } from "react";

// Validated categorical palette (dataviz reference instance), fixed order, light/dark steps.
const LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];
const DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];

// Cost categories keep the same slot everywhere, so color follows the entity, never its rank.
export const CATEGORY_SLOT = {
  lightweight_model: 0,
  larger_model: 1,
  human_review: 2,
  tool_api: 3,
  evaluation: 4,
  other_variable: 5,
  infrastructure: 6,
};

export function useChartTheme() {
  const q = typeof window !== "undefined" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  const [dark, setDark] = useState(q ? q.matches : false);
  useEffect(() => {
    if (!q) return;
    const on = (e) => setDark(e.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, []);
  return {
    dark,
    series: dark ? DARK : LIGHT,
    grid: dark ? "#2c2c2a" : "#e1e0d9",
    axis: dark ? "#383835" : "#c3c2b7",
    muted: "#898781",
    ink2: dark ? "#c3c2b7" : "#52514e",
    surface: dark ? "#1a1a19" : "#fcfcfb",
    critical: "#d03b3b",
  };
}

export function catColor(theme, key) {
  return theme.series[CATEGORY_SLOT[key] ?? 7];
}
