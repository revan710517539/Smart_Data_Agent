import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export type FollowUpVisual = {
  visualization_spec?: Record<string, unknown>;
  rows?: Array<Record<string, unknown>>;
  field_labels?: Record<string, string>;
};

export function WorkspaceFollowUpChart({ visual }: { visual?: FollowUpVisual }) {
  const chart = buildFollowUpChart(visual);
  if (!chart) return null;
  const ChartTag = chart.kind === "line" ? LineChart : BarChart;
  return (
    <div className="mt-2 rounded-lg border border-[#ececf0] bg-[#fafbfc] px-2 pb-2 pt-2" data-workspace-follow-up-chart="true">
      <div className="px-1 text-[10px] text-[#636366]">{chart.title}</div>
      <div className="h-[160px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ChartTag data={chart.points} margin={{ top: 8, right: 6, bottom: 28, left: -18 }}>
            <CartesianGrid stroke="#ececf0" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 9, fill: "#8a8a8e" }} angle={-24} textAnchor="end" interval={0} />
            <YAxis tick={{ fontSize: 9, fill: "#8a8a8e" }} />
            <Tooltip contentStyle={{ border: "1px solid #e5e5ea", borderRadius: 8, fontSize: 11 }} />
            {chart.kind === "line"
              ? <Line type="monotone" dataKey="value" name={chart.metric} stroke="#5b8def" strokeWidth={2} dot={{ r: 2.5 }} />
              : <Bar dataKey="value" name={chart.metric} fill="#5b8def" radius={[4, 4, 0, 0]} />}
          </ChartTag>
        </ResponsiveContainer>
      </div>
      <div className="px-1 text-[9px] text-[#aeaeb2]">维度：{chart.dimension} · 指标：{chart.metric}</div>
    </div>
  );
}

export function followUpVisualFromRefs(refs: Array<Record<string, unknown>> | undefined): FollowUpVisual | undefined {
  const match = (refs || []).find((item) => item && (item.type === "follow_up_visual" || item.visualization_spec || Array.isArray(item.rows)));
  if (!match) return undefined;
  return {
    visualization_spec: match.visualization_spec && typeof match.visualization_spec === "object" && !Array.isArray(match.visualization_spec) ? match.visualization_spec as Record<string, unknown> : {},
    rows: Array.isArray(match.rows) ? match.rows.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object" && !Array.isArray(row)) : [],
    field_labels: match.field_labels && typeof match.field_labels === "object" && !Array.isArray(match.field_labels) ? match.field_labels as Record<string, string> : {},
  };
}

function buildFollowUpChart(visual?: FollowUpVisual) {
  const rows = visual?.rows || [];
  if (!rows.length) return null;
  const spec = visual?.visualization_spec || {};
  const labels = visual?.field_labels || {};
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row).filter((key) => key !== "_visual_source" && !key.startsWith("_")))));
  const specY = Array.isArray(spec.y) ? spec.y.map(String) : spec.y ? [String(spec.y)] : [];
  const metric = specY.find((item) => rows.some((row) => numericValue(row[item]) !== null))
    || columns.find((column) => rows.some((row) => numericValue(row[column]) !== null));
  if (!metric) return null;
  const specX = String(spec.x || "");
  const series = String(spec.series || "");
  const dimension = (specX && specX !== metric ? specX : columns.find((column) => column !== metric)) || metric;
  const points = rows.slice(0, 12).map((row, index) => {
    const dimLabel = String(row[dimension] ?? `第${index + 1}项`);
    const seriesLabel = series && row[series] != null ? String(row[series]) : "";
    return {
      label: seriesLabel ? `${seriesLabel} ${dimLabel}` : dimLabel,
      value: numericValue(row[metric]) || 0,
    };
  });
  const kind = ["line", "area"].includes(String(spec.chart_type || "")) ? "line" : "bar";
  return {
    kind,
    title: String(spec.title || "分析图表"),
    dimension: labels[dimension] || dimension,
    metric: labels[metric] || metric,
    points,
  };
}

function numericValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const parsed = Number(String(value ?? "").replace(/,/g, "").match(/-?\d+(?:\.\d+)?/)?.[0]);
  return Number.isFinite(parsed) ? parsed : null;
}
