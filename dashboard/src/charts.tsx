import { memo, useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart, ScatterChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";
import type { Snapshot } from "./types";
import { THEME, ACCENT, ACCENT_SOFT, MUTED_LINE } from "./theme";

echarts.use([LineChart, ScatterChart, GridComponent, LegendComponent, TooltipComponent, DataZoomComponent, CanvasRenderer]);

export function Chart({ option, label, className = "chart" }: { option: EChartsCoreOption; label: string; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, THEME, { renderer: "canvas" });
    chart.setOption(option);
    // resize with the card (grid columns change width without a window resize)
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.dispose();
    };
  }, [option]);
  return <div ref={ref} className={className} role="img" aria-label={label} />;
}

// ECharts passes undefined (not null) for padded points; guard every formatter.
export const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
export const tipMoney = (v: unknown) => (isNum(v) ? `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "–");
const pctFmt = (v: unknown) => (isNum(v) ? `${v.toFixed(2)}%` : "–");

// Drag to pan, Ctrl/Shift + wheel (or pinch) to zoom, so plain scrolling still scrolls the page.
export const zoom = (slider: boolean) => [
  { type: "inside", xAxisIndex: 0, zoomOnMouseWheel: "ctrl", moveOnMouseWheel: "shift", moveOnMouseMove: true },
  ...(slider ? [{ type: "slider", xAxisIndex: 0, height: 18, bottom: 4, brushSelect: false }] : []),
];

type Row = { label: string; value: string; color?: string };
const tipHtml = (date: string, rows: Row[]) =>
  `<div style="font-weight:600;margin-bottom:4px">${date}</div>` +
  rows.map((r) => `<div style="display:flex;gap:12px;justify-content:space-between"><span>${r.color ? `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${r.color};margin-right:6px"></span>` : ""}${r.label}</span><b>${r.value}</b></div>`).join("");

const axisMoney = { type: "value" as const, axisLabel: { formatter: (v: number) => `$${v.toLocaleString("en-US")}` } };

export const MarginTrend = memo(function MarginTrend({ snap }: { snap: Snapshot }) {
  const option: EChartsCoreOption = {
    tooltip: { trigger: "axis", axisPointer: { type: "cross", label: { show: false } }, valueFormatter: pctFmt },
    grid: { left: 8, right: 16, top: 24, bottom: 36, containLabel: true },
    dataZoom: zoom(true),
    xAxis: { type: "category", data: snap.trend.map((d) => d.date) },
    yAxis: { type: "value", min: (v: { min: number }) => Math.floor(v.min - 0.5), max: 100, axisLabel: { formatter: "{value}%" } },
    series: [{
      name: "AI gross margin", type: "line", showSymbol: false, color: ACCENT,
      data: snap.trend.map((d) => (d.ai_gross_margin_pct === null ? null : +(d.ai_gross_margin_pct * 100).toFixed(2))),
    }],
  };
  return <Chart option={option} label="Daily AI gross margin percentage over the simulated window" />;
});

export const CogsForecast = memo(function CogsForecast({ snap }: { snap: Snapshot }) {
  const recent = snap.trend.slice(-30);
  const pts = snap.forecast.points;
  const dates = [...recent.map((d) => d.date), ...pts.map((p) => p.date)];
  const pad = (n: number) => Array(n).fill(null);
  const option: EChartsCoreOption = {
    tooltip: {
      trigger: "axis",
      formatter: (ps: { dataIndex: number }[]) => {
        const i = ps[0]?.dataIndex ?? 0;
        if (i < recent.length) return tipHtml(dates[i], [{ label: "Actual AI cost to serve", value: tipMoney(recent[i].ai_cost_to_serve_usd), color: MUTED_LINE }]);
        const p = pts[i - recent.length];
        return tipHtml(dates[i], [
          { label: "Forecast P50", value: tipMoney(p.p50), color: ACCENT },
          { label: "P10", value: tipMoney(p.p10) },
          { label: "P90", value: tipMoney(p.p90) },
        ]);
      },
    },
    legend: { data: ["Actual AI cost to serve", "Forecast P50", "P10–P90"], top: 0, type: "scroll" },
    grid: { left: 8, right: 16, top: 40, bottom: 8, containLabel: true },
    dataZoom: zoom(false),
    xAxis: { type: "category", data: dates },
    yAxis: axisMoney,
    series: [
      { name: "Actual AI cost to serve", type: "line", showSymbol: false, color: MUTED_LINE, data: [...recent.map((d) => d.ai_cost_to_serve_usd), ...pad(pts.length)] },
      { name: "P10 base", type: "line", stack: "band", symbol: "none", lineStyle: { opacity: 0 }, tooltip: { show: false },
        data: [...pad(recent.length), ...pts.map((p) => p.p10)] },
      // The band height (P90 - P10) is a chart drawing aid, not a reported figure.
      { name: "P10–P90", type: "line", stack: "band", symbol: "none", lineStyle: { opacity: 0 }, areaStyle: { color: ACCENT_SOFT, opacity: 1 },
        color: ACCENT_SOFT, tooltip: { show: false }, data: [...pad(recent.length), ...pts.map((p) => +(p.p90 - p.p10).toFixed(2))] },
      { name: "Forecast P50", type: "line", showSymbol: false, color: ACCENT, lineStyle: { type: "dashed" },
        data: [...pad(recent.length), ...pts.map((p) => p.p50)] },
    ],
  };
  return <Chart option={option} label="Last 30 days of AI cost to serve and the 30-day forecast with its P10 to P90 band" />;
});

export const MarginForecast = memo(function MarginForecast({ snap }: { snap: Snapshot }) {
  const f = snap.m2_margin_forecast;
  if (!f || f.points.length === 0) return null;
  const recent = snap.trend.slice(-30);
  const pts = f.points;
  const dates = [...recent.map((d) => d.date), ...pts.map((p) => p.date)];
  const pad = (n: number) => Array(n).fill(null);
  const pct = (v: number | null) => (v === null ? null : +(v * 100).toFixed(2));
  const option: EChartsCoreOption = {
    tooltip: {
      trigger: "axis",
      formatter: (ps: { dataIndex: number }[]) => {
        const i = ps[0]?.dataIndex ?? 0;
        if (i < recent.length) return tipHtml(dates[i], [{ label: "Actual margin", value: pctFmt(pct(recent[i].ai_gross_margin_pct)), color: MUTED_LINE }]);
        const p = pts[i - recent.length];
        return tipHtml(dates[i], [
          { label: "Forecast margin", value: pctFmt(pct(p.mid)), color: ACCENT },
          { label: "Low", value: pctFmt(pct(p.low)) },
          { label: "High", value: pctFmt(pct(p.high)) },
        ]);
      },
    },
    legend: { data: ["Actual margin", "Forecast margin", "Margin band"], top: 0, type: "scroll" },
    grid: { left: 8, right: 16, top: 40, bottom: 8, containLabel: true },
    dataZoom: zoom(false),
    xAxis: { type: "category", data: dates },
    yAxis: { type: "value", scale: true, axisLabel: { formatter: "{value}%" } },
    series: [
      { name: "Actual margin", type: "line", showSymbol: false, color: MUTED_LINE, data: [...recent.map((d) => pct(d.ai_gross_margin_pct)), ...pad(pts.length)] },
      { name: "Band base", type: "line", stack: "band", symbol: "none", lineStyle: { opacity: 0 }, tooltip: { show: false }, data: [...pad(recent.length), ...pts.map((p) => pct(p.low))] },
      // The band height (high - low) is a chart drawing aid, not a reported figure.
      { name: "Margin band", type: "line", stack: "band", symbol: "none", lineStyle: { opacity: 0 }, areaStyle: { color: ACCENT_SOFT, opacity: 1 },
        color: ACCENT_SOFT, tooltip: { show: false }, data: [...pad(recent.length), ...pts.map((p) => (p.low === null || p.high === null ? null : +((p.high - p.low) * 100).toFixed(2)))] },
      { name: "Forecast margin", type: "line", showSymbol: false, color: ACCENT, lineStyle: { type: "dashed" }, data: [...pad(recent.length), ...pts.map((p) => pct(p.mid))] },
    ],
  };
  return <Chart option={option} label="Last 30 days of AI gross margin and the 30-day margin forecast band" />;
});
