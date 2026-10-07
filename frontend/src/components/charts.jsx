import React from "react";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useChartTheme } from "../lib/colors.js";
import { compact, fmtValue } from "../lib/format.js";

export function ChartTooltip({ active, payload, label, cur, kind = "money", labelFmt }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tooltip">
      <div className="t">{labelFmt ? labelFmt(label, payload) : label}</div>
      {payload.map((p) => (
        <div key={p.dataKey + p.name}>
          <span className="swatch" style={{ background: p.payload?.color || p.color || p.fill }} />
          {p.name}: <b>{fmtValue(p.value, p.payload?.kind || kind, cur)}</b>
        </div>
      ))}
    </div>
  );
}

// Horizontal bars: one row per category, colored by entity slot.
export function HBars({ data, cur, kind = "money", height, valueName = "Cost" }) {
  const t = useChartTheme();
  const h = height ?? Math.max(120, data.length * 36 + 30);
  return (
    <div style={{ height: h }}>
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 56, bottom: 4, left: 8 }} barCategoryGap={8}>
          <CartesianGrid horizontal={false} stroke={t.grid} />
          <XAxis type="number" tickFormatter={(v) => compact(v, cur)} stroke={t.axis} tick={{ fill: t.muted, fontSize: 11 }} />
          <YAxis type="category" dataKey="label" width={170} stroke={t.axis} tick={{ fill: t.ink2, fontSize: 12 }} />
          <Tooltip cursor={{ fill: t.grid, opacity: 0.4 }} content={<ChartTooltip cur={cur} kind={kind} />} />
          <Bar dataKey="value" name={valueName} maxBarSize={22} radius={[0, 4, 4, 0]}
            label={{ position: "right", fill: t.ink2, fontSize: 11, formatter: (v) => compact(v, cur) }}>
            {data.map((d, i) => <Cell key={i} fill={d.color} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function VolumeLine({ data, cur }) {
  const t = useChartTheme();
  return (
    <div className="chart-box">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 10, right: 20, bottom: 4, left: 8 }}>
          <CartesianGrid vertical={false} stroke={t.grid} />
          <XAxis dataKey="tasks" type="number" domain={[0, "dataMax"]} tickFormatter={(v) => compact(v)} stroke={t.axis}
            tick={{ fill: t.muted, fontSize: 11 }} label={{ value: "Tasks per month", position: "insideBottomRight", offset: -2, fill: t.muted, fontSize: 11 }} />
          <YAxis tickFormatter={(v) => compact(v, cur)} stroke={t.axis} tick={{ fill: t.muted, fontSize: 11 }} width={64} />
          <Tooltip content={<ChartTooltip cur={cur} labelFmt={(l, p) => `${p[0].payload.label} current volume · ${Math.round(p[0].payload.tasks).toLocaleString()} tasks/mo`} />} />
          <Line dataKey="monthly" name="Monthly cost" stroke={t.series[0]} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: t.surface, fill: t.series[0] }} activeDot={{ r: 6 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// Grouped vertical bars for scenario comparison: one measure, one bar per scenario.
export function ScenarioBars({ data, cur, kind = "unit_money", height = 240 }) {
  const t = useChartTheme();
  return (
    <div style={{ height }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 18, right: 12, bottom: 4, left: 8 }}>
          <CartesianGrid vertical={false} stroke={t.grid} />
          <XAxis dataKey="name" stroke={t.axis} tick={{ fill: t.ink2, fontSize: 11 }} interval={0} />
          <YAxis tickFormatter={(v) => compact(v, kind.includes("money") ? cur : null)} stroke={t.axis} tick={{ fill: t.muted, fontSize: 11 }} width={64} />
          <Tooltip cursor={{ fill: t.grid, opacity: 0.4 }} content={<ChartTooltip cur={cur} kind={kind} />} />
          <Bar dataKey="value" name="Value" maxBarSize={24} radius={[4, 4, 0, 0]}
            label={{ position: "top", fill: t.ink2, fontSize: 11, formatter: (v) => fmtValue(v, kind, cur) }}>
            {data.map((d, i) => <Cell key={i} fill={t.series[i % 8]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// Stacked monthly breakdown per scenario (categories keep fixed slots).
export function StackedBreakdown({ data, keys, cur, labels, colorFor }) {
  const t = useChartTheme();
  return (
    <div style={{ height: 280 }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 10, right: 12, bottom: 4, left: 8 }}>
          <CartesianGrid vertical={false} stroke={t.grid} />
          <XAxis dataKey="name" stroke={t.axis} tick={{ fill: t.ink2, fontSize: 11 }} interval={0} />
          <YAxis tickFormatter={(v) => compact(v, cur)} stroke={t.axis} tick={{ fill: t.muted, fontSize: 11 }} width={64} />
          <Tooltip cursor={{ fill: t.grid, opacity: 0.4 }} content={<ChartTooltip cur={cur} kind="money" />} />
          {keys.map((k, i) => (
            <Bar key={k} dataKey={k} name={labels[k]} stackId="a" fill={colorFor(k)} maxBarSize={36}
              stroke={t.surface} strokeWidth={2}
              radius={i === keys.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
