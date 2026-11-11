// "Mission control" chart theme: dark glass, cyan signal lines, faint grid. Charts read these, CSS reads styles.css.
import * as echarts from "echarts/core";

export const THEME = "mc";
export const ACCENT = "#22d3ee"; // signal cyan
export const ACCENT_SOFT = "rgba(34, 211, 238, 0.22)";
export const MUTED_LINE = "#8b9bb4";
const TEXT = "#c8d5e8";
const GRID = "rgba(125, 211, 252, 0.10)";

echarts.registerTheme(THEME, {
  backgroundColor: "transparent",
  color: [ACCENT, "#a78bfa", "#34d399", "#f472b6", "#fbbf24"],
  textStyle: { color: TEXT, fontFamily: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif' },
  legend: { textStyle: { color: TEXT } },
  tooltip: {
    backgroundColor: "rgba(8, 15, 30, 0.92)", borderColor: "rgba(34, 211, 238, 0.45)", borderWidth: 1,
    textStyle: { color: "#e6f1ff" }, extraCssText: "box-shadow: 0 0 18px rgba(34, 211, 238, 0.18); border-radius: 8px;",
  },
  categoryAxis: {
    axisLine: { lineStyle: { color: "rgba(125, 211, 252, 0.35)" } }, axisTick: { show: false },
    axisLabel: { color: "#8fa3bf" }, splitLine: { show: false },
  },
  valueAxis: {
    axisLine: { show: false }, axisLabel: { color: "#8fa3bf" },
    splitLine: { lineStyle: { color: GRID, type: "dashed" } },
  },
  line: { lineStyle: { width: 2 }, symbol: "none" },
});
