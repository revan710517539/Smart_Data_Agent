import type { MetricDictionaryItem } from "../../data/metricDictionary";
import type { AnalysisDataTableSelection } from "./domain";

export type MetricPreset = {
  status: "resolved" | "incomplete" | "suggestions" | "none";
  message: string;
  metrics: MetricDictionaryItem[];
  table?: AnalysisDataTableSelection;
};

function normalized(value: string) {
  return value.trim().toLocaleLowerCase();
}

function metricMatchesQuestion(metric: MetricDictionaryItem, question: string) {
  const target = normalized(question);
  const name = normalized(metric.metricName);
  const shortName = name.split("（", 1)[0].split("(", 1)[0].trim();
  const code = normalized(metric.metricCode || "");
  const aliases = code === "loan_amount" ? ["放款"] : [];
  return [name, shortName, code, ...aliases].some((candidate) => candidate.length >= 2 && target.includes(candidate));
}

const GENERIC_QUERY_TERMS = new Set(["分析", "数据", "指标", "查询", "看看", "问题", "情况", "目前", "本月", "本周", "今天"]);

function relevantTerms(value: string) {
  const chunks = normalized(value).match(/[\u4e00-\u9fff]{2,}|[a-z0-9_]{2,}/g) || [];
  return new Set(chunks.flatMap((chunk) => {
    if (/^[\u4e00-\u9fff]+$/.test(chunk)) {
      return Array.from({ length: Math.max(0, chunk.length - 1) }, (_, index) => chunk.slice(index, index + 2));
    }
    return [chunk];
  }).filter((term) => !GENERIC_QUERY_TERMS.has(term)));
}

function relatedMetrics(question: string, metrics: MetricDictionaryItem[]) {
  const questionTerms = relevantTerms(question);
  return metrics
    .map((metric) => {
      const name = normalized(metric.metricName);
      const detail = normalized(`${metric.definition} ${metric.description} ${metric.applicationScene}`);
      const score = Array.from(questionTerms).reduce((total, term) => (
        total + (name.includes(term) ? 4 : 0) + (detail.includes(term) ? 1 : 0)
      ), 0);
      return { metric, score };
    })
    .filter(({ score }) => score >= 4)
    .sort((left, right) => right.score - left.score || left.metric.metricName.localeCompare(right.metric.metricName, "zh-CN"))
    .slice(0, 3)
    .map(({ metric }) => metric);
}

function tableSupportsMetric(table: AnalysisDataTableSelection, metric: MetricDictionaryItem) {
  const datasetId = metric.datasetId?.trim();
  const tableDataset = table.datasetId?.trim();
  return Boolean(
    datasetId && (
      datasetId === tableDataset
      || datasetId === table.code
      || datasetId === table.id
      || Boolean(metric.metricCode && table.metricCodes?.includes(metric.metricCode))
    ),
  );
}

function missingExecutionConfiguration(metric: MetricDictionaryItem) {
  const missing: string[] = [];
  if (!metric.valueLogic.trim()) missing.push("取值逻辑");
  if (!metric.sourceTable.trim() && !metric.datasetId?.trim()) missing.push("取值表名");
  if (!missing.length && (!metric.metricCode?.trim() || metric.semanticStatus !== "published")) {
    missing.push("可执行口径");
  }
  return missing;
}

export function resolveMetricPreset(
  question: string,
  metrics: MetricDictionaryItem[],
  tables: AnalysisDataTableSelection[],
): MetricPreset {
  if (!question.trim()) return { status: "none", message: "", metrics: [] };
  const directMatches = metrics.filter((metric) => metricMatchesQuestion(metric, question)).slice(0, 3);
  const matches = directMatches.length ? directMatches : relatedMetrics(question, metrics);
  const executable = matches.filter(
    (metric) => metric.semanticStatus === "published" && Boolean(metric.metricCode && metric.datasetId),
  );
  const resolvedMetric = executable.find((metric) => tables.some((table) => tableSupportsMetric(table, metric)));
  if (resolvedMetric) {
    const table = tables.find((candidate) => tableSupportsMetric(candidate, resolvedMetric));
    if (table) {
      return {
        status: "resolved",
        message: `已识别已登记指标“${resolvedMetric.metricName}”，提交后将使用“${table.name}”按指标口径统计。`,
        metrics: [resolvedMetric],
        table,
      };
    }
  }
  if (directMatches.length) {
    const metric = directMatches[0];
    const missing = missingExecutionConfiguration(metric);
    return {
      status: "incomplete",
      message: missing.length
        ? `已识别指标字典中的“${metric.metricName}”，但该指标缺少${missing.join("、")}，当前无法执行。`
        : `已识别指标字典中的“${metric.metricName}”，但当前机构没有与该指标绑定的可用数据表，当前无法执行。`,
      metrics: [metric],
    };
  }
  if (matches.length) {
    return {
      status: "suggestions",
      message: `未找到可执行的数据表映射。可查看相关指标：${matches.map((metric) => metric.metricName).join("、")}；或选择对应数据表。`,
      metrics: matches,
    };
  }
  return {
    status: "none",
    message: "目前没有与问题匹配的已登记指标。请选择对应数据表；系统会先核对指标字典，不会擅自改用其他数据源。",
    metrics: [],
  };
}

export function metricDefinitionText(definition: Record<string, unknown> | undefined) {
  if (!definition) return "未登记口径：本次结果未绑定指标字典定义，请结合已选数据表字段和执行计划复核。";
  const metricName = String(definition.metric_name || definition.metricName || definition.metric_code || "指标");
  const aggregation = String(definition.aggregation || definition.aggregationType || "sum");
  const numerator = String(definition.numerator || definition.numeratorField || "");
  const denominator = String(definition.denominator || definition.denominatorField || "");
  const formula = aggregation === "ratio" && numerator && denominator
    ? `${numerator} / ${denominator}`
    : `${aggregation}(${String(definition.metric_code || definition.metricCode || metricName)})`;
  const grain = String(definition.grain || "当前数据表粒度");
  const source = String(definition.source || definition.definitionSource || "指标字典");
  return `${source === "temporary_table_schema" ? "临时口径" : "指标字典口径"}：${metricName} = ${formula}；统计粒度：${grain}。`;
}
