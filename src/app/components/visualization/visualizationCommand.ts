import type { VisualizationType } from "../self-analysis/domain";

export type VisualizationVoiceResolution = {
  visualizationType: VisualizationType | null;
  metricField: string;
  dimensionField: string;
  dataVisibility: "shown" | "hidden" | null;
};

export function resolveVisualizationVoiceCommand(
  command: string,
  numericFields: string[],
  dimensionFields: string[],
  labels: Record<string, string>,
): VisualizationVoiceResolution {
  const mentionedMetric = findMentionedField(command, numericFields, labels);
  const mentionedDimension = findMentionedField(command, dimensionFields, labels);
  return {
    visualizationType: resolveVisualizationType(command),
    metricField: mentionedMetric || (/指标|数值|度量|纵轴|按.+(?:展示|画|生成).*(?:趋势|图)/.test(command) ? mentionedMetric : ""),
    dimensionField: mentionedDimension || (/维度|横轴|分类|按.+(?:分组|拆分)/.test(command) ? mentionedDimension : ""),
    dataVisibility: /显示.*数据|显示.*数值|打开.*标签/.test(command)
      ? "shown"
      : /隐藏.*数据|隐藏.*数值|关闭.*标签/.test(command)
        ? "hidden"
        : null,
  };
}

export function moveVisualizationField(fields: string[], source: string, target: string) {
  const from = fields.indexOf(source);
  const to = fields.indexOf(target);
  if (from < 0 || to < 0 || from === to) return fields;
  const next = [...fields];
  next.splice(from, 1);
  next.splice(to, 0, source);
  return next;
}

function findMentionedField(command: string, fields: string[], labels: Record<string, string>) {
  const normalizedCommand = normalizeFieldText(command);
  return [...fields]
    .sort((left, right) => (labels[right] || right).length - (labels[left] || left).length)
    .find((field) => [field, labels[field]].filter(Boolean).some((candidate) => normalizedCommand.includes(normalizeFieldText(String(candidate))))) || "";
}

function normalizeFieldText(value: string) {
  return value.toLowerCase().replace(/[\s_()（）\-—:：，,。]/g, "");
}

function resolveVisualizationType(command: string): VisualizationType | null {
  const matches: Array<[RegExp, VisualizationType]> = [
    [/多维表|交叉表|透视表/, "pivot"], [/明细表|数据表|表格/, "table"], [/组合图|柱线/, "combo"],
    [/堆叠/, "stacked_bar"], [/柱状图|纵向柱|柱形图/, "column"], [/条形图|横向柱/, "bar"],
    [/折线图|趋势图|趋势线|走势(?:图)?/, "line"], [/面积图/, "area"], [/环形图|饼图/, "donut"],
    [/散点图/, "scatter"], [/漏斗图/, "funnel"], [/矩形树图|树图/, "treemap"],
    [/雷达图/, "radar"], [/指标卡|KPI/i, "kpi"],
  ];
  return matches.flatMap(([pattern, type]) => {
    const match = command.match(pattern);
    return match?.index === undefined ? [] : [{ index: match.index, type }];
  }).sort((left, right) => right.index - left.index)[0]?.type || null;
}
