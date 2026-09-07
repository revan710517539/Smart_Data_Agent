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

export type VisualizationRankDirection = "desc" | "asc";

export type VisualizationMetricRankConfig = {
  metricField: string;
  direction: VisualizationRankDirection;
};

export type VisualizationMetricFormatConfig = {
  metricField: string;
  percent: boolean;
  decimalPlaces?: number;
};

export type VisualizationAssociationOperator = "gt" | "gte" | "eq" | "lte" | "lt";
export type VisualizationAssociationSource = "metric" | "progress";
export type VisualizationAssociationStyle = "background" | "text" | "value";
export type VisualizationProgressColorMode = "gradient" | "reverse_gradient" | "solid";
export type VisualizationProgressDenominatorMode = "selected_row" | "column_max";

export type VisualizationAssociationRule = {
  id: string;
  source: VisualizationAssociationSource;
  operator: VisualizationAssociationOperator;
  threshold: number;
  targetField: string;
  style: VisualizationAssociationStyle;
  color: string;
  replacementValue?: string;
};

export type VisualizationMetricProgressConfig = {
  metricField: string;
  denominatorMode?: VisualizationProgressDenominatorMode;
  denominatorRules: VisualizationFilterRule[];
  color: string;
  colorEnd?: string;
  colorMode?: VisualizationProgressColorMode;
  associationRules: VisualizationAssociationRule[];
};

export type VisualizationCalculatedColumnConfig = {
  id: string;
  name: string;
  position: number;
  expression: string;
};

export type VisualizationTableFont = "system" | "humanist" | "serif" | "mono";
export type VisualizationTableDensity = "compact" | "comfortable";

export type VisualizationTableStyleConfig = {
  templateId: string;
  headerBackground: string;
  headerTextColor: string;
  headerBorderColor: string;
  bodyBackground: string;
  alternateRowBackground: string;
  bodyTextColor: string;
  borderColor: string;
  accentColor: string;
  totalBackground: string;
  totalTextColor: string;
  fontFamily: VisualizationTableFont;
  density: VisualizationTableDensity;
  bandedRows: boolean;
  emphasizeFirstColumn: boolean;
};

export type VisualizationChartFont = "system" | "humanist" | "mono";
export type VisualizationChartHeight = "compact" | "standard" | "expanded";
export type VisualizationChartBarWidth = "slim" | "standard" | "wide";

export type VisualizationChartStyleConfig = {
  templateId: string;
  backgroundColor: string;
  plotBackgroundColor: string;
  textColor: string;
  mutedTextColor: string;
  gridColor: string;
  axisColor: string;
  palette: string[];
  fontFamily: VisualizationChartFont;
  chartHeight: VisualizationChartHeight;
  lineWidth: number;
  pointRadius: number;
  barRadius: number;
  barWidth: VisualizationChartBarWidth;
  areaOpacity: number;
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
  mergedDimensionFields?: string[];
  frozenColumnFields?: string[];
  frozenRowKeys?: string[];
  metricRankings?: VisualizationMetricRankConfig[];
  metricFormats?: VisualizationMetricFormatConfig[];
  metricProgress?: VisualizationMetricProgressConfig[];
  calculatedColumns?: VisualizationCalculatedColumnConfig[];
  tableStyle?: VisualizationTableStyleConfig;
  chartStyle?: VisualizationChartStyleConfig;
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
  borderless?: boolean;
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

export function visualizationRoleFields(
  fields: string[],
  fieldMetadata: Record<string, FieldDisplayMetadata> = {},
  inferredMetrics: string[] = [],
) {
  const inferred = new Set(inferredMetrics);
  const hasDeclaredRoles = fields.some((field) => {
    const role = fieldMetadata[field]?.semanticRole;
    return role === "metric" || role === "dimension" || role === "date" || Boolean(fieldMetadata[field]?.isMetric);
  });
  const metrics: string[] = [];
  const dimensions: string[] = [];
  for (const field of fields) {
    const meta = fieldMetadata[field];
    const role = meta?.semanticRole;
    if (role === "metric" || (Boolean(meta?.isMetric) && role !== "dimension" && role !== "date")) {
      metrics.push(field);
      continue;
    }
    if (role === "dimension" || role === "date") {
      dimensions.push(field);
      continue;
    }
    if (hasDeclaredRoles) continue;
    if (inferred.has(field)) metrics.push(field);
    else dimensions.push(field);
  }
  return { metrics, dimensions };
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

export function orderedTableFields(dimensionFields: string[], metricFields: string[], frozenColumnFields: string[] = []) {
  const all = selectedTableFields(dimensionFields, metricFields);
  const frozen = unique(frozenColumnFields.filter((field) => all.includes(field)));
  return [...frozen, ...all.filter((field) => !frozen.includes(field))];
}

export function groupRowsForMergedDimensions(rows: AnalysisRow[], dimensionFields: string[], mergedDimensionFields: string[]) {
  const activeFields = unique(mergedDimensionFields.filter(Boolean));
  if (!activeFields.length) return rows;
  return rows
    .map((row, index) => ({ row, index }))
    .sort((left, right) => {
      for (const field of activeFields) {
        const compared = displayValue(left.row.raw[field]).localeCompare(displayValue(right.row.raw[field]), "zh-CN", { numeric: true });
        if (compared) return compared;
      }
      return left.index - right.index;
    })
    .map(({ row }) => row);
}

export function mergedDimensionCellSpan(rows: AnalysisRow[], rowIndex: number, field: string, dimensionFields: string[], mergedDimensionFields: string[]) {
  const activeFields = unique(mergedDimensionFields.filter(Boolean));
  const activeIndex = activeFields.indexOf(field);
  if (activeIndex < 0 || rowIndex < 0 || rowIndex >= rows.length) return 1;
  const groupFields = activeFields.slice(0, activeIndex + 1);
  const sameGroup = (left: AnalysisRow, right: AnalysisRow) => groupFields.every((candidate) => displayValue(left.raw[candidate]) === displayValue(right.raw[candidate]));
  if (rowIndex > 0 && sameGroup(rows[rowIndex - 1], rows[rowIndex])) return 0;
  let span = 1;
  while (rowIndex + span < rows.length && sameGroup(rows[rowIndex], rows[rowIndex + span])) span += 1;
  return span;
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

export function normalizeMetricRankings(configs: VisualizationMetricRankConfig[] = [], metricFields: string[] = []) {
  const allowed = new Set(metricFields);
  const seen = new Set<string>();
  return configs.filter((config) => {
    if (!config?.metricField || seen.has(config.metricField) || (allowed.size && !allowed.has(config.metricField))) return false;
    seen.add(config.metricField);
    return true;
  }).map((config) => ({ metricField: config.metricField, direction: config.direction === "asc" ? "asc" as const : "desc" as const }));
}

export function normalizeMetricFormats(configs: VisualizationMetricFormatConfig[] = [], metricFields: string[] = []) {
  const allowed = new Set(metricFields);
  const seen = new Set<string>();
  return configs.slice(0, 100).flatMap((config): VisualizationMetricFormatConfig[] => {
    const metricField = String(config?.metricField || "").slice(0, 300);
    if (!metricField || seen.has(metricField) || (allowed.size && !allowed.has(metricField))) return [];
    seen.add(metricField);
    const parsedPlaces = config.decimalPlaces === undefined || config.decimalPlaces === null
      ? undefined
      : Math.max(0, Math.min(8, Math.trunc(Number(config.decimalPlaces))));
    const decimalPlaces = Number.isFinite(parsedPlaces) ? parsedPlaces : undefined;
    const percent = Boolean(config.percent);
    return percent || decimalPlaces !== undefined ? [{ metricField, percent, ...(decimalPlaces !== undefined ? { decimalPlaces } : {}) }] : [];
  });
}

export function normalizeMetricProgress(configs: VisualizationMetricProgressConfig[] = [], metricFields: string[] = []) {
  const allowed = new Set(metricFields);
  const seen = new Set<string>();
  return configs.filter((config) => {
    if (!config?.metricField || seen.has(config.metricField) || (allowed.size && !allowed.has(config.metricField))) return false;
    seen.add(config.metricField);
    return true;
  }).map((config) => ({
    metricField: config.metricField,
    denominatorMode: config.denominatorMode === "column_max" ? "column_max" as const : "selected_row" as const,
    denominatorRules: normalizeVisualizationFilterGroups([{ id: `progress-${config.metricField}`, rules: config.denominatorRules || [] }])[0]?.rules || [],
    color: normalizeHexColor(config.color, "#2c7be5"),
    colorEnd: normalizeHexColor(config.colorEnd, normalizeHexColor(config.color, "#2c7be5")),
    colorMode: config.colorMode === "solid" ? "solid" as const : config.colorMode === "reverse_gradient" ? "reverse_gradient" as const : "gradient" as const,
    associationRules: (config.associationRules || []).filter((rule) => rule && Number.isFinite(Number(rule.threshold))).map((rule, index) => ({
      id: rule.id || `association-${config.metricField}-${index}`,
      source: rule.source === "progress" ? "progress" as const : "metric" as const,
      operator: (["gt", "gte", "eq", "lte", "lt"] as VisualizationAssociationOperator[]).includes(rule.operator) ? rule.operator : "gte" as const,
      threshold: Number(rule.threshold),
      targetField: rule.targetField || config.metricField,
      style: rule.style === "text" ? "text" as const : rule.style === "value" ? "value" as const : "background" as const,
      color: normalizeHexColor(rule.color, "#fff1b8"),
      replacementValue: String(rule.replacementValue || "").slice(0, 120),
    })),
  }));
}

export function normalizeCalculatedColumns(configs: VisualizationCalculatedColumnConfig[] = []) {
  const seen = new Set<string>();
  return configs.slice(0, 20).filter((config) => {
    if (!config?.id || seen.has(config.id)) return false;
    seen.add(config.id);
    return true;
  }).map((config, index) => ({
    id: String(config.id).slice(0, 160),
    name: String(config.name || `新增列${index + 1}`).trim().slice(0, 80) || `新增列${index + 1}`,
    position: Math.max(0, Math.min(200, Number.isFinite(Number(config.position)) ? Math.trunc(Number(config.position)) : index)),
    expression: String(config.expression || "").trim().slice(0, 2000),
  }));
}

type FormulaToken = { kind: "number" | "field" | "word" | "operator" | "left" | "right" | "comma" | "end"; value: string; offset: number };
type FormulaNode =
  | { kind: "number"; value: number }
  | { kind: "field"; field: string }
  | { kind: "unary"; operator: "+" | "-"; value: FormulaNode }
  | { kind: "binary"; operator: string; left: FormulaNode; right: FormulaNode }
  | { kind: "function"; name: "SUM" | "AVERAGE" | "COUNT"; arguments: FormulaNode[] }
  | { kind: "case"; condition: FormulaNode; whenTrue: FormulaNode; whenFalse: FormulaNode };

export type VisualizationFormulaEvaluation = { value: number | null; error: string | null };
export type CompiledVisualizationFormula = { error: string | null; evaluate: (values: Record<string, unknown>) => VisualizationFormulaEvaluation };

function tokenizeVisualizationFormula(source: string): FormulaToken[] {
  const tokens: FormulaToken[] = [];
  let index = 0;
  while (index < source.length) {
    const character = source[index];
    if (/\s/.test(character)) { index += 1; continue; }
    if (character === "[") {
      const close = source.indexOf("]", index + 1);
      if (close < 0) throw new Error(`第 ${index + 1} 位缺少 ]`);
      const field = source.slice(index + 1, close).trim();
      if (!field) throw new Error(`第 ${index + 1} 位指标名为空`);
      tokens.push({ kind: "field", value: field, offset: index });
      index = close + 1;
      continue;
    }
    const numberMatch = source.slice(index).match(/^(?:\d+(?:\.\d*)?|\.\d+)/);
    if (numberMatch) { tokens.push({ kind: "number", value: numberMatch[0], offset: index }); index += numberMatch[0].length; continue; }
    const wordMatch = source.slice(index).match(/^[A-Za-z_][A-Za-z0-9_]*/);
    if (wordMatch) { tokens.push({ kind: "word", value: wordMatch[0].toUpperCase(), offset: index }); index += wordMatch[0].length; continue; }
    const two = source.slice(index, index + 2);
    if ([">=", "<=", "<>", "!="].includes(two)) { tokens.push({ kind: "operator", value: two, offset: index }); index += 2; continue; }
    if (["+", "-", "*", "/", ">", "<", "="].includes(character)) { tokens.push({ kind: "operator", value: character, offset: index }); index += 1; continue; }
    if (character === "(") tokens.push({ kind: "left", value: character, offset: index });
    else if (character === ")") tokens.push({ kind: "right", value: character, offset: index });
    else if (character === ",") tokens.push({ kind: "comma", value: character, offset: index });
    else throw new Error(`第 ${index + 1} 位包含不支持的符号 ${character}`);
    index += 1;
  }
  tokens.push({ kind: "end", value: "", offset: source.length });
  return tokens;
}

class VisualizationFormulaParser {
  private index = 0;
  constructor(private readonly tokens: FormulaToken[], private readonly allowedFields: Map<string, string>) {}
  parse() {
    const expression = this.parseComparison();
    if (this.peek().kind !== "end") this.fail(`无法识别 ${this.peek().value || "结尾"}`);
    return expression;
  }
  private peek() { return this.tokens[this.index]; }
  private take() { return this.tokens[this.index++]; }
  private fail(message: string): never { throw new Error(`第 ${this.peek().offset + 1} 位${message}`); }
  private match(kind: FormulaToken["kind"], value?: string) {
    const token = this.peek();
    if (token.kind !== kind || (value !== undefined && token.value !== value)) return false;
    this.index += 1;
    return true;
  }
  private expect(kind: FormulaToken["kind"], value?: string) {
    if (!this.match(kind, value)) this.fail(`应为 ${value || kind}`);
  }
  private parseComparison(): FormulaNode {
    let left = this.parseAdditive();
    const token = this.peek();
    if (token.kind === "operator" && [">", ">=", "<", "<=", "=", "<>", "!="].includes(token.value)) {
      this.take();
      left = { kind: "binary", operator: token.value, left, right: this.parseAdditive() };
    }
    return left;
  }
  private parseAdditive(): FormulaNode {
    let left = this.parseMultiplicative();
    while (this.peek().kind === "operator" && ["+", "-"].includes(this.peek().value)) {
      const operator = this.take().value;
      left = { kind: "binary", operator, left, right: this.parseMultiplicative() };
    }
    return left;
  }
  private parseMultiplicative(): FormulaNode {
    let left = this.parseUnary();
    while (this.peek().kind === "operator" && ["*", "/"].includes(this.peek().value)) {
      const operator = this.take().value;
      left = { kind: "binary", operator, left, right: this.parseUnary() };
    }
    return left;
  }
  private parseUnary(): FormulaNode {
    if (this.peek().kind === "operator" && ["+", "-"].includes(this.peek().value)) {
      const operator = this.take().value as "+" | "-";
      return { kind: "unary", operator, value: this.parseUnary() };
    }
    return this.parsePrimary();
  }
  private parsePrimary(): FormulaNode {
    const token = this.peek();
    if (this.match("number")) return { kind: "number", value: Number(token.value) };
    if (this.match("field")) {
      const field = this.allowedFields.get(token.value);
      if (!field) throw new Error(`指标 [${token.value}] 不在当前表格中`);
      return { kind: "field", field };
    }
    if (this.match("left")) { const expression = this.parseComparison(); this.expect("right"); return expression; }
    if (token.kind === "word" && token.value === "CASE") return this.parseCase();
    if (token.kind === "word" && ["SUM", "AVERAGE", "COUNT"].includes(token.value)) return this.parseFunction();
    this.fail(`缺少数字、指标或函数`);
  }
  private parseFunction(): FormulaNode {
    const name = this.take().value as "SUM" | "AVERAGE" | "COUNT";
    this.expect("left");
    const args: FormulaNode[] = [];
    if (!this.match("right")) {
      do { args.push(this.parseComparison()); } while (this.match("comma"));
      this.expect("right");
    }
    if (!args.length) throw new Error(`${name} 至少需要一个参数`);
    return { kind: "function", name, arguments: args };
  }
  private parseCase(): FormulaNode {
    this.expect("word", "CASE");
    this.expect("word", "WHEN");
    const condition = this.parseComparison();
    this.expect("word", "THEN");
    const whenTrue = this.parseComparison();
    this.expect("word", "ELSE");
    const whenFalse = this.parseComparison();
    this.expect("word", "END");
    return { kind: "case", condition, whenTrue, whenFalse };
  }
}

function formulaNumericValue(value: unknown) {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const parsed = typeof value === "number" ? value : Number(String(value).replace(/,/g, "").replace(/%$/, ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function evaluateFormulaNode(node: FormulaNode, values: Record<string, unknown>): number | null {
  if (node.kind === "number") return node.value;
  if (node.kind === "field") return formulaNumericValue(values[node.field]);
  if (node.kind === "unary") { const value = evaluateFormulaNode(node.value, values); return value === null ? null : node.operator === "-" ? -value : value; }
  if (node.kind === "function") {
    const args = node.arguments.map((argument) => evaluateFormulaNode(argument, values));
    if (node.name === "COUNT") return args.filter((value) => value !== null).length;
    const numeric = args.filter((value): value is number => value !== null);
    if (!numeric.length) return null;
    const sum = numeric.reduce((total, value) => total + value, 0);
    return node.name === "AVERAGE" ? sum / numeric.length : sum;
  }
  if (node.kind === "case") return evaluateFormulaNode(node.condition, values) ? evaluateFormulaNode(node.whenTrue, values) : evaluateFormulaNode(node.whenFalse, values);
  const left = evaluateFormulaNode(node.left, values);
  const right = evaluateFormulaNode(node.right, values);
  if ([">", ">=", "<", "<=", "=", "<>", "!="].includes(node.operator)) {
    if (left === null || right === null) return 0;
    if (node.operator === ">") return left > right ? 1 : 0;
    if (node.operator === ">=") return left >= right ? 1 : 0;
    if (node.operator === "<") return left < right ? 1 : 0;
    if (node.operator === "<=") return left <= right ? 1 : 0;
    if (node.operator === "=") return Math.abs(left - right) < 1e-9 ? 1 : 0;
    return Math.abs(left - right) >= 1e-9 ? 1 : 0;
  }
  if (left === null || right === null) return null;
  if (node.operator === "+") return left + right;
  if (node.operator === "-") return left - right;
  if (node.operator === "*") return left * right;
  if (right === 0) throw new Error("除数不能为 0");
  return left / right;
}

export function compileVisualizationFormula(expression: string, metricFields: string[], labels: Record<string, string> = {}): CompiledVisualizationFormula {
  const source = String(expression || "").trim();
  if (!source) return { error: "请输入计算规则", evaluate: () => ({ value: null, error: null }) };
  try {
    const allowedFields = new Map(metricFields.map((field) => [field, field]));
    const labelCounts = new Map<string, number>();
    metricFields.forEach((field) => { const label = String(labels[field] || "").trim(); if (label) labelCounts.set(label, (labelCounts.get(label) || 0) + 1); });
    metricFields.forEach((field) => { const label = String(labels[field] || "").trim(); if (label && labelCounts.get(label) === 1) allowedFields.set(label, field); });
    const node = new VisualizationFormulaParser(tokenizeVisualizationFormula(source), allowedFields).parse();
    return {
      error: null,
      evaluate: (values) => {
        try {
          const value = evaluateFormulaNode(node, values);
          return value === null || !Number.isFinite(value) ? { value: null, error: value === null ? null : "计算结果不是有效数值" } : { value, error: null };
        } catch (error) { return { value: null, error: error instanceof Error ? error.message : "计算失败" }; }
      },
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : "公式格式不正确";
    return { error: message, evaluate: () => ({ value: null, error: message }) };
  }
}

export function ordinalRanks<T>(items: T[], valueFor: (item: T) => unknown, direction: VisualizationRankDirection = "desc") {
  const ranked = items.map((item, index) => ({ item, index, value: nullableNumericValue(valueFor(item)) }));
  ranked.sort((left, right) => {
    if (left.value === null && right.value === null) return left.index - right.index;
    if (left.value === null) return 1;
    if (right.value === null) return -1;
    const compared = direction === "asc" ? left.value - right.value : right.value - left.value;
    return compared || left.index - right.index;
  });
  return new Map(ranked.map((entry, rankIndex) => [entry.item, rankIndex + 1]));
}

export function resolveProgressDenominator(rows: AnalysisRow[], config: VisualizationMetricProgressConfig, candidateValues?: unknown[]) {
  if (config.denominatorMode === "column_max") {
    const values = (candidateValues || rows.map((row) => row.raw[config.metricField]))
      .map(nullableNumericValue)
      .filter((value): value is number => value !== null && Number.isFinite(value));
    if (!values.length) return { status: "non_numeric" as const, matches: [] as AnalysisRow[], value: null as number | null };
    const value = Math.max(...values);
    if (value === 0) return { status: "zero" as const, matches: [] as AnalysisRow[], value };
    if (value < 0) return { status: "non_positive" as const, matches: [] as AnalysisRow[], value: null as number | null };
    return { status: "ready" as const, matches: [] as AnalysisRow[], value };
  }
  const rules = normalizeVisualizationFilterGroups([{ id: "progress-denominator", rules: config.denominatorRules || [] }])[0]?.rules || [];
  if (!rules.length || rules.some((rule) => !rule.field || rule.values.length !== 1)) return { status: "incomplete" as const, matches: [] as AnalysisRow[], value: null as number | null };
  const matches = filterVisualizationRows(rows, {}, [{ id: "progress-denominator", rules }]);
  if (matches.length !== 1) return { status: matches.length ? "multiple" as const : "missing" as const, matches, value: null as number | null };
  const value = nullableNumericValue(matches[0].raw[config.metricField]);
  if (value === null) return { status: "non_numeric" as const, matches, value };
  if (value === 0) return { status: "zero" as const, matches, value };
  return { status: "ready" as const, matches, value };
}

export function progressPercentage(numerator: unknown, denominator: number | null) {
  const numeric = nullableNumericValue(numerator);
  if (numeric === null || denominator === null || !Number.isFinite(denominator) || denominator === 0) return null;
  return numeric / denominator * 100;
}

export function associationRuleMatches(rule: VisualizationAssociationRule, metricValue: unknown, progressValue: number | null) {
  const actual = rule.source === "progress" ? progressValue : nullableNumericValue(metricValue);
  if (actual === null || !Number.isFinite(actual)) return false;
  if (rule.operator === "gt") return actual > rule.threshold;
  if (rule.operator === "gte") return actual >= rule.threshold;
  if (rule.operator === "eq") return Math.abs(actual - rule.threshold) < 1e-9;
  if (rule.operator === "lte") return actual <= rule.threshold;
  return actual < rule.threshold;
}

export function normalizeHexColor(value: unknown, fallback = "#2c7be5") {
  const normalized = String(value || "").trim();
  return /^#[0-9a-f]{6}$/i.test(normalized) ? normalized.toLowerCase() : fallback;
}

export const defaultVisualizationTableStyle: VisualizationTableStyleConfig = {
  templateId: "sda-clean",
  headerBackground: "#F5FAF7",
  headerTextColor: "#536B5E",
  headerBorderColor: "#DCE7DF",
  bodyBackground: "#FFFFFF",
  alternateRowBackground: "#F8FBF9",
  bodyTextColor: "#343B37",
  borderColor: "#E7ECE9",
  accentColor: "#3F8F68",
  totalBackground: "#EAF3EE",
  totalTextColor: "#294E3B",
  fontFamily: "system",
  density: "comfortable",
  bandedRows: true,
  emphasizeFirstColumn: false,
};

export function normalizeVisualizationTableStyle(value?: Partial<VisualizationTableStyleConfig> | null): VisualizationTableStyleConfig {
  const source = value || {};
  const fontFamily: VisualizationTableFont = (["system", "humanist", "serif", "mono"] as VisualizationTableFont[]).includes(source.fontFamily as VisualizationTableFont) ? source.fontFamily as VisualizationTableFont : "system";
  return {
    templateId: String(source.templateId || defaultVisualizationTableStyle.templateId).trim().slice(0, 120) || defaultVisualizationTableStyle.templateId,
    headerBackground: normalizeHexColor(source.headerBackground, defaultVisualizationTableStyle.headerBackground),
    headerTextColor: normalizeHexColor(source.headerTextColor, defaultVisualizationTableStyle.headerTextColor),
    headerBorderColor: normalizeHexColor(source.headerBorderColor, defaultVisualizationTableStyle.headerBorderColor),
    bodyBackground: normalizeHexColor(source.bodyBackground, defaultVisualizationTableStyle.bodyBackground),
    alternateRowBackground: normalizeHexColor(source.alternateRowBackground, defaultVisualizationTableStyle.alternateRowBackground),
    bodyTextColor: normalizeHexColor(source.bodyTextColor, defaultVisualizationTableStyle.bodyTextColor),
    borderColor: normalizeHexColor(source.borderColor, defaultVisualizationTableStyle.borderColor),
    accentColor: normalizeHexColor(source.accentColor, defaultVisualizationTableStyle.accentColor),
    totalBackground: normalizeHexColor(source.totalBackground, defaultVisualizationTableStyle.totalBackground),
    totalTextColor: normalizeHexColor(source.totalTextColor, defaultVisualizationTableStyle.totalTextColor),
    fontFamily,
    density: source.density === "compact" ? "compact" : "comfortable",
    bandedRows: source.bandedRows !== false,
    emphasizeFirstColumn: source.emphasizeFirstColumn === true,
  };
}

export const defaultVisualizationChartStyle: VisualizationChartStyleConfig = {
  templateId: "chart-jade",
  backgroundColor: "#FBFDFC",
  plotBackgroundColor: "#FFFFFF",
  textColor: "#34443C",
  mutedTextColor: "#7F8F87",
  gridColor: "#E7EEE9",
  axisColor: "#CFDAD3",
  palette: ["#287557", "#5F8173", "#617988", "#84958B", "#526F65", "#A18B62", "#8C9992", "#A1ABA5"],
  fontFamily: "system",
  chartHeight: "standard",
  lineWidth: 2,
  pointRadius: 2.5,
  barRadius: 4,
  barWidth: "standard",
  areaOpacity: 0.1,
};

export function normalizeVisualizationChartStyle(value?: Partial<VisualizationChartStyleConfig> | null): VisualizationChartStyleConfig {
  const source = value || {};
  const palette = Array.isArray(source.palette)
    ? source.palette.map((color) => normalizeHexColor(color, "")).filter(Boolean).slice(0, 12)
    : [];
  const fontFamily = (["system", "humanist", "mono"] as VisualizationChartFont[]).includes(source.fontFamily as VisualizationChartFont) ? source.fontFamily as VisualizationChartFont : defaultVisualizationChartStyle.fontFamily;
  const chartHeight = (["compact", "standard", "expanded"] as VisualizationChartHeight[]).includes(source.chartHeight as VisualizationChartHeight) ? source.chartHeight as VisualizationChartHeight : defaultVisualizationChartStyle.chartHeight;
  const barWidth = (["slim", "standard", "wide"] as VisualizationChartBarWidth[]).includes(source.barWidth as VisualizationChartBarWidth) ? source.barWidth as VisualizationChartBarWidth : defaultVisualizationChartStyle.barWidth;
  const bounded = (raw: unknown, fallback: number, minimum: number, maximum: number) => {
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? Math.max(minimum, Math.min(maximum, parsed)) : fallback;
  };
  return {
    templateId: String(source.templateId || defaultVisualizationChartStyle.templateId).trim().slice(0, 120) || defaultVisualizationChartStyle.templateId,
    backgroundColor: normalizeHexColor(source.backgroundColor, defaultVisualizationChartStyle.backgroundColor),
    plotBackgroundColor: normalizeHexColor(source.plotBackgroundColor, defaultVisualizationChartStyle.plotBackgroundColor),
    textColor: normalizeHexColor(source.textColor, defaultVisualizationChartStyle.textColor),
    mutedTextColor: normalizeHexColor(source.mutedTextColor, defaultVisualizationChartStyle.mutedTextColor),
    gridColor: normalizeHexColor(source.gridColor, defaultVisualizationChartStyle.gridColor),
    axisColor: normalizeHexColor(source.axisColor, defaultVisualizationChartStyle.axisColor),
    palette: palette.length >= 2 ? palette : [...defaultVisualizationChartStyle.palette],
    fontFamily,
    chartHeight,
    lineWidth: bounded(source.lineWidth, defaultVisualizationChartStyle.lineWidth, 1, 4),
    pointRadius: bounded(source.pointRadius, defaultVisualizationChartStyle.pointRadius, 0, 6),
    barRadius: bounded(source.barRadius, defaultVisualizationChartStyle.barRadius, 0, 12),
    barWidth,
    areaOpacity: bounded(source.areaOpacity, defaultVisualizationChartStyle.areaOpacity, 0, 0.4),
  };
}

export function readableTextColor(background: string) {
  const color = normalizeHexColor(background).slice(1);
  const [red, green, blue] = [0, 2, 4].map((offset) => Number.parseInt(color.slice(offset, offset + 2), 16));
  return (red * 299 + green * 587 + blue * 114) / 1000 < 142 ? "#ffffff" : "#1d1d1f";
}

function nullableNumericValue(value: unknown) {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const parsed = typeof value === "number" ? value : Number(String(value).replace(/,/g, "").replace(/%$/, ""));
  return Number.isFinite(parsed) ? parsed : null;
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
