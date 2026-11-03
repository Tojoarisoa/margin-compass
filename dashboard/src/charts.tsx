import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";
import type { Snapshot } from "./types";

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

function Chart({ option, label }: { option: EChartsCoreOption; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chart.setOption(option);
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [option]);
  return <div ref={ref} className="chart" role="img" aria-label={label} />;
}

const axisMoney = { type: "value" as const, axisLabel: { formatter: (v: number) => `$${v.toLocaleString("en-US")}` } };

export function MarginTrend({ snap }: { snap: Snapshot }) {
  const option: EChartsCoreOption = {
    tooltip: { trigger: "axis", valueFormatter: (v: number) => `${v.toFixed(2)}%` },
    grid: { left: 56, right: 16, top: 24, bottom: 32 },
    xAxis: { type: "category", data: snap.trend.map((d) => d.date) },
    yAxis: { type: "value", min: (v: { min: number }) => Math.floor(v.min - 0.5), max: 100, axisLabel: { formatter: "{value}%" } },
    series: [{
      name: "AI gross margin", type: "line", showSymbol: false, color: "#2563eb",
      data: snap.trend.map((d) => (d.ai_gross_margin_pct === null ? null : +(d.ai_gross_margin_pct * 100).toFixed(2))),
    }],
  };
  return <Chart option={option} label="Daily AI gross margin percentage over the simulated window" />;
}

export function CogsForecast({ snap }: { snap: Snapshot }) {
  const recent = snap.trend.slice(-30);
  const pts = snap.forecast.points;
  const dates = [...recent.map((d) => d.date), ...pts.map((p) => p.date)];
  const pad = (n: number) => Array(n).fill(null);
  const option: EChartsCoreOption = {
    tooltip: { trigger: "axis", valueFormatter: (v: number | null) => (v === null ? "" : `$${v.toFixed(2)}`) },
    legend: { data: ["Actual AI cost to serve", "Forecast P50", "P10–P90"], bottom: 0 },
    grid: { left: 56, right: 16, top: 16, bottom: 48 },
    xAxis: { type: "category", data: dates },
    yAxis: axisMoney,
    series: [
      { name: "Actual AI cost to serve", type: "line", showSymbol: false, color: "#64748b", data: [...recent.map((d) => d.ai_cost_to_serve_usd), ...pad(pts.length)] },
      { name: "P10 base", type: "line", stack: "band", symbol: "none", lineStyle: { opacity: 0 }, tooltip: { show: false },
        data: [...pad(recent.length), ...pts.map((p) => p.p10)] },
      // The band height (P90 - P10) is a chart drawing aid, not a reported figure.
      { name: "P10–P90", type: "line", stack: "band", symbol: "none", lineStyle: { opacity: 0 }, areaStyle: { color: "#93c5fd", opacity: 0.5 },
        color: "#93c5fd", tooltip: { show: false }, data: [...pad(recent.length), ...pts.map((p) => +(p.p90 - p.p10).toFixed(2))] },
      { name: "Forecast P50", type: "line", showSymbol: false, color: "#2563eb", lineStyle: { type: "dashed" },
        data: [...pad(recent.length), ...pts.map((p) => p.p50)] },
    ],
  };
  return <Chart option={option} label="Last 30 days of AI cost to serve and the 30-day forecast with its P10 to P90 band" />;
}
