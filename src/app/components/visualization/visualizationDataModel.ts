import type { AnalysisRow, VisualizationType } from "../self-analysis/domain";
import type { FieldDisplayMetadata } from "../../data/fieldSemantics";
import type { RichNoteItem } from "../notes/richNote";

export type VisualizationFilters = Record<string, string[]>;

export type VisualizationFilterOperator = "in" | "not_in" | "contains" | "not_contains";

export type VisualizationFilterRule = {
  id: string;
  field: string;
  operator: VisualizationFilterOperator;
  values: string[];
};

export type VisualizationFilterGroup = {
  id: string;
  rules: VisualizationFilterRule[];
};

export const visualizationFilterOperators: Array<{ value: VisualizationFilterOperator; label: string }> = [
  { value: "in", label: "等于其中任一" },
  { value: "not_in", label: "不等于任一" },
  { value: "contains", label: "包含" },
  { value: "not_contains", label: "不包含" },
];

export type VisualizationCardConfig = {
  metricFields: string[];
  dimensionFields: string[];
  filters: VisualizationFilters;
  filterGroups: VisualizationFilterGroup[];
  sumFilteredRows: boolean;
  comboLineFields: string[];
  noteTitle?: string;
  noteBody?: string;
  noteTitleHidden?: boolean;
  noteItems?: RichNoteItem[];
  layoutSpan?: number;
  layoutHeight?: number;
  maxLayoutSpan?: number;
  maxLayoutHeight?: number;
};

export type VisualDataPoint = {
  key: string;
  label: string;
  values: Record<string, number>;
  rows: AnalysisRow[];
};

export type VisualizationFieldPolicy = {
  minimumMetrics: number;
  maximumMetrics: number;
  maximumDimensions: number;
  defaultMetricCount: number;
  defaultDimensionCount: number;
  preferTimeDimension: boolean;
};

const unlimited = Number.MAX_SAFE_INTEGER;

export function visualizationFieldPolicy(type: VisualizationType): VisualizationFieldPolicy {
  if (type === "scatter") return { minimumMetrics: 2, maximumMetrics: 2, maximumDimensions: unlimited, defaultMetricCount: 2, defaultDimensionCount: 1, preferTimeDimension: false };
  if (type === "treemap") return { minimumMetrics: 1, maximumMetrics: 1, maximumDimensions: unlimited, defaultMetricCount: 1, defaultDimensionCount: 1, preferTimeDimension: false };
  if (type === "text") return { minimumMetrics: 0, maximumMetrics: unlimited, maximumDimensions: unlimited, defaultMetricCount: 0, defaultDimensionCount: 0, preferTimeDimension: false };
  if (type === "kpi") return { minimumMetrics: 1, maximumMetrics: unlimited, maximumDimensions: 1, defaultMetricCount: 4, defaultDimensionCount: 0, preferTimeDimension: false };
  if (type === "table" || type === "pivot") return { minimumMetrics: 1, maximumMetrics: unlimited, maximumDimensions: unlimited, defaultMetricCount: 4, defaultDimensionCount: 2, preferTimeDimension: false };
  if (type === "line" || type === "area") return { minimumMetrics: 1, maximumMetrics: unlimited, maximumDimensions: unlimited, defaultMetricCount: 4, defaultDimensionCount: 1, preferTimeDimension: true };
  return { minimumMetrics: 1, maximumMetrics: unlimited, maximumDimensions: unlimited, defaultMetricCount: 4, defaultDimensionCount: 1, preferTimeDimension: false };
}

export function defaultVisualizationSelections(
  type: VisualizationType,
  metricCandidates: string[],
  dimensionCandidates: string[],
  labels: Record<string, string>,
  fieldMetadata: Record<string, FieldDisplayMetadata> = {},
) {
  const policy = visualizationFieldPolicy(type);
  const metrics = metricCandidates.slice(0, Math.min(policy.defaultMetricCount, policy.maximumMetrics));
  const timeDimension = policy.preferTimeDimension
    ? dimensionCandidates.find((field) => fieldMetadata[field]?.semanticRole === "date" || fieldMetadata[field]?.isTime)
      || dimensionCandidates.find((field) => /日期|时间|年月|季度|月份|周|date|time|month|year|quarter/i.test(`${field} ${labels[field] || ""}`))
    : undefined;
  const primaryDimension = policy.preferTimeDimension
    ? dimensionCandidates.find((field) => fieldMetadata[field]?.isPrimaryKey)
    : undefined;
  const dimensions = policy.defaultDimensionCount === 0
    ? []
    : [timeDimension || primaryDimension || dimensionCandidates[0], ...dimensionCandidates.filter((field) => field !== timeDimension && field !== primaryDimension && field !== dimensionCandidates[0])]
      .filter((field): field is string => Boolean(field))
      .slice(0, Math.min(policy.defaultDimensionCount, policy.maximumDimensions));
  return { metrics, dimensions };
}

export function normalizeVisualizationSelections(
  type: VisualizationType,
  currentMetrics: string[],
  currentDimensions: string[],
  metricCandidates: string[],
  dimensionCandidates: string[],
  labels: Record<string, string>,
  fieldMetadata: Record<string, FieldDisplayMetadata> = {},
) {
  const policy = visualizationFieldPolicy(type);
  const defaults = defaultVisualizationSelections(type, metricCandidates, dimensionCandidates, labels, fieldMetadata);
  let metrics = unique(currentMetrics.filter((field) => metricCandidates.includes(field))).slice(0, policy.maximumMetrics);
  let dimensions = unique(currentDimensions.filter((field) => dimensionCandidates.includes(field))).slice(0, policy.maximumDimensions);
  if (metrics.length < policy.minimumMetrics) {
    metrics = unique([...metrics, ...defaults.metrics, ...metricCandidates]).slice(0, Math.max(policy.minimumMetrics, Math.min(policy.defaultMetricCount, policy.maximumMetrics)));
  }
  if (!currentDimensions.length && policy.defaultDimensionCount > 0 && !dimensions.length) dimensions = defaults.dimensions;
  return { metrics, dimensions };
}

export function toggleVisualizationField(
  kind: "metric" | "dimension",
  type: VisualizationType,
  current: string[],
  field: string,
) {
  const policy = visualizationFieldPolicy(type);
  const minimum = kind === "metric" ? policy.minimumMetrics : 0;
  const maximum = kind === "metric" ? policy.maximumMetrics : policy.maximumDimensions;
  if (current.includes(field)) return current.length > minimum ? current.filter((item) => item !== field) : current;
  const next = [...current, field];
  if (next.length <= maximum) return next;
  return maximum === 1 ? [field] : next.slice(next.length - maximum);
}

export function moveVisualizationFieldWithinGroup(fields: string[], source: string, target: string) {
  if (!fields.includes(source) || !fields.includes(target) || source === target) return fields;
  const next = fields.filter((field) => field !== source);
  next.splice(next.indexOf(target), 0, source);
  return next;
}

export function selectedTableFields(dimensionFields: string[], metricFields: string[]) {
  return [...unique(dimensionFields), ...unique(metricFields.filter((field) => !dimensionFields.includes(field)))];
}

export function dimensionCombination(row: AnalysisRow, dimensionFields: string[]) {
  if (!dimensionFields.length) return "全部";
  return dimensionFields.map((field) => displayValue(row.raw[field])).join(" · ");
}

export function legacyFiltersToFilterGroups(filters: VisualizationFilters): VisualizationFilterGroup[] {
  const rules = Object.entries(filters)
    .filter(([, values]) => Array.isArray(values) && values.length)
    .map(([field, values], index) => ({ id: `legacy-rule-${index}`, field, operator: "in" as const, values: unique(values) }));
  return rules.length ? [{ id: "legacy-group", rules }] : [];
}

export function normalizeVisualizationFilterGroups(groups: VisualizationFilterGroup[]): VisualizationFilterGroup[] {
  return groups
    .map((group, groupIndex) => ({
      id: group.id || `filter-group-${groupIndex}`,
      rules: (group.rules || [])
        .filter((rule) => Boolean(rule.field) || Boolean(rule.values?.length))
        .map((rule, ruleIndex) => ({
          id: rule.id || `filter-rule-${groupIndex}-${ruleIndex}`,
          field: rule.field || "",
          operator: visualizationFilterOperators.some((option) => option.value === rule.operator) ? rule.operator : "in",
          values: unique(Array.isArray(rule.values) ? rule.values.map(String) : []),
        })),
    }))
    .filter((group) => group.rules.length);
}

export function visualizationFilterGroupsToLegacyFilters(groups: VisualizationFilterGroup[]): VisualizationFilters {
  const normalized = normalizeVisualizationFilterGroups(groups);
  if (normalized.length !== 1 || normalized[0].rules.some((rule) => rule.operator !== "in" || !rule.field)) return {};
  return Object.fromEntries(normalized[0].rules.map((rule) => [rule.field, rule.values]));
}

export function filterVisualizationRows(rows: AnalysisRow[], filters: VisualizationFilters, filterGroups: VisualizationFilterGroup[] = []) {
  const groups = normalizeVisualizationFilterGroups(filterGroups);
  if (groups.length) return rows.filter((row) => groups.some((group) => group.rules.every((rule) => filterRuleMatches(row, rule))));
  const active = Object.entries(filters).filter(([, values]) => values.length);
  if (!active.length) return rows;
  return rows.filter((row) => active.every(([field, values]) => values.includes(displayValue(row.raw[field]))));
}

export function visualizationFilterValues(rows: AnalysisRow[], field: string) {
  return unique(rows.map((row) => displayValue(row.raw[field]))).slice(0, 200);
}

export function buildVisualDataPoints(
  rows: AnalysisRow[],
  metricFields: string[],
  dimensionFields: string[],
  filters: VisualizationFilters,
  sumRows: boolean,
  filterGroups: VisualizationFilterGroup[] = [],
): VisualDataPoint[] {
  const filtered = filterVisualizationRows(rows, filters, filterGroups);
  if (!sumRows) {
    return filtered.map((row, index) => ({
      key: `${dimensionCombination(row, dimensionFields)}\u0000${index}`,
      label: dimensionCombination(row, dimensionFields),
      values: Object.fromEntries(metricFields.map((field) => [field, numericValue(row.raw[field])])),
      rows: [row],
    }));
  }
  const groups = new Map<string, VisualDataPoint>();
  filtered.forEach((row) => {
    const label = dimensionCombination(row, dimensionFields);
    const current = groups.get(label) || { key: label, label, values: Object.fromEntries(metricFields.map((field) => [field, 0])), rows: [] };
    metricFields.forEach((field) => { current.values[field] = (current.values[field] || 0) + numericValue(row.raw[field]); });
    current.rows.push(row);
    groups.set(label, current);
  });
  return [...groups.values()];
}

export function metricTotal(rows: AnalysisRow[], field: string, filters: VisualizationFilters, filterGroups: VisualizationFilterGroup[] = []) {
  return filterVisualizationRows(rows, filters, filterGroups).reduce((sum, row) => sum + numericValue(row.raw[field]), 0);
}

const mutedChartPalette = ["#287557", "#5f8173", "#71877e", "#617988", "#84958b", "#526f65", "#8c9992", "#a1aba5"];

export function visualizationChartColor(index: number) {
  return mutedChartPalette[Math.abs(index) % mutedChartPalette.length];
}

export function defaultComboLineFields(metricFields: string[], current: string[]) {
  const retained = current.filter((field) => metricFields.includes(field));
  return retained.length ? retained : metricFields.slice(0, 1);
}

export function numericValue(value: unknown) {
  const parsed = typeof value === "number" ? value : Number(String(value ?? "").replace(/,/g, "").replace(/%$/, ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

function displayValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "未分类";
  return String(value);
}

function filterRuleMatches(row: AnalysisRow, rule: VisualizationFilterRule) {
  if (!rule.field || !rule.values.length || !Object.prototype.hasOwnProperty.call(row.raw, rule.field)) return false;
  const actual = displayValue(row.raw[rule.field]);
  if (rule.operator === "in") return rule.values.includes(actual);
  if (rule.operator === "not_in") return !rule.values.includes(actual);
  if (rule.operator === "contains") return rule.values.some((value) => actual.includes(value));
  return rule.values.every((value) => !actual.includes(value));
}

function unique<T>(items: T[]) {
  return Array.from(new Set(items));
}
