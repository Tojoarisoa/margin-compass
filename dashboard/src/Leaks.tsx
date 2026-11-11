// PG-3 "Margin Leaks" tab (M3-05). Reads publish/latest/pg3.json: detector output and the daily LLM cost per feature.
// Every figure is computed by the pipeline; this file only formats and draws. The RCA narrative arrives with the agent (M4).
import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { DataZoomComponent, MarkAreaComponent, GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { money } from "./format";
import { tipMoney, zoom } from "./charts";
import { THEME, ACCENT } from "./theme";

echarts.use([LineChart, GridComponent, MarkAreaComponent, TooltipComponent, DataZoomComponent, CanvasRenderer]);

interface Leak { feature_id: string; metric: string; start_date: string; detected_date: string; end_date: string | null; impact_usd_per_day: number; peak_ratio: number; status: string }
interface Pg3 { leaks: Leak[]; daily_llm_cost: { date: string; feature_id: string; llm_cost_usd: number }[]; open_leaks: number; open_impact_usd_per_day: number }

function CostChart({ pg3, feature }: { pg3: Pg3; feature: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const rows = useMemo(() => pg3.daily_llm_cost.filter((r) => r.feature_id === feature), [pg3, feature]);
  const leaks = useMemo(() => pg3.leaks.filter((l) => l.feature_id === feature), [pg3, feature]);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, THEME, { renderer: "canvas" });
    chart.setOption({
      tooltip: { trigger: "axis", valueFormatter: tipMoney },
      grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
      dataZoom: zoom(false),
      xAxis: { type: "category", data: rows.map((r) => r.date) },
      yAxis: { type: "value", axisLabel: { formatter: (v: number) => `$${v.toLocaleString("en-US")}` } },
      series: [{
        name: "LLM cost per day", type: "line", showSymbol: false, color: ACCENT, data: rows.map((r) => r.llm_cost_usd),
        markArea: { itemStyle: { color: "rgba(220,38,38,0.12)" },
          data: leaks.map((l) => [{ xAxis: l.start_date }, { xAxis: l.end_date ?? rows[rows.length - 1]?.date ?? l.start_date }]) },
      }],
    });
    const ro = new ResizeObserver(() => chart.resize());  // resize with the card, not only the window
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [rows, leaks]);
  return <div ref={ref} className="chart" role="img" aria-label={`Daily LLM cost for ${feature}; detected leaks are shaded`} />;
}

export default function Leaks() {
  const [pg3, setPg3] = useState<Pg3 | null>(null);
  const [failed, setFailed] = useState(false);
  const [feature, setFeature] = useState("");
  useEffect(() => {
    fetch("/publish/latest/pg3.json", { cache: "no-cache" })
      .then((r) => (r.ok ? (r.json() as Promise<Pg3>) : Promise.reject(new Error(String(r.status)))))
      .then((d) => { setPg3(d); setFeature(d.leaks[0]?.feature_id ?? ""); })
      .catch(() => setFailed(true));
  }, []);
  if (failed) return <p className="muted">No leak data yet. It appears after the next data build.</p>;
  if (!pg3) return <p className="muted">Loading…</p>;
  if (pg3.leaks.length === 0) return <p className="muted">No margin leaks detected in the window.</p>;
  const features = [...new Set(pg3.leaks.map((l) => l.feature_id))];
  return (
    <div>
      <p className="muted small">{pg3.open_leaks} open leak(s), {money(pg3.open_impact_usd_per_day)} per day while they last. Detected from daily LLM cost per feature; shaded areas on the chart are the detected leaks.</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th scope="col">Feature</th><th scope="col">Status</th><th scope="col">Started</th><th scope="col">Detected</th>
              <th scope="col">Ended</th><th scope="col" className="num">Impact per day</th><th scope="col" className="num">Peak vs normal</th></tr>
          </thead>
          <tbody>
            {pg3.leaks.map((l) => (
              <tr key={`${l.feature_id}-${l.start_date}`}>
                <td>{l.feature_id}</td><td>{l.status}</td><td>{l.start_date}</td><td>{l.detected_date}</td><td>{l.end_date ?? "ongoing"}</td>
                <td className="num">{money(l.impact_usd_per_day)}</td><td className="num">{l.peak_ratio.toFixed(1)}x</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <label className="small">Feature{" "}
        <select value={feature} onChange={(e) => setFeature(e.target.value)}>
          {features.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
      </label>
      {feature && <CostChart pg3={pg3} feature={feature} />}
    </div>
  );
}
