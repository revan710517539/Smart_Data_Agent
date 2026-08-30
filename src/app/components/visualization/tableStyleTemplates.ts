import {
  compileVisualizationFormula,
  normalizeCalculatedColumns,
  normalizeMetricFormats,
  normalizeMetricProgress,
  normalizeMetricRankings,
  normalizeVisualizationTableStyle,
  type VisualizationCalculatedColumnConfig,
  type VisualizationCardConfig,
  type VisualizationMetricProgressConfig,
  type VisualizationMetricFormatConfig,
  type VisualizationMetricRankConfig,
  type VisualizationTableStyleConfig,
} from "./visualizationDataModel";

export type BuiltInTableTemplate = {
  id: string;
  name: string;
  sourceLabel: string;
  style: VisualizationTableStyleConfig;
  progressColors: readonly [string, string];
};

const style = (value: Partial<VisualizationTableStyleConfig> & Pick<VisualizationTableStyleConfig, "templateId">) => normalizeVisualizationTableStyle(value);

// Independently authored design-token sets informed by Excel table-style
// anatomy and the public GitHub theme patterns cited in the product research.
// No upstream CSS, markup, images or runtime dependency are copied.
export const builtInTableTemplates: BuiltInTableTemplate[] = [
  { id: "excel-navy", name: "深海排名", sourceLabel: "Excel · 参考图", progressColors: ["#5A9BD5", "#C9E2F5"], style: style({ templateId: "excel-navy", headerBackground: "#245680", headerTextColor: "#FFFFFF", headerBorderColor: "#8EB6D8", bodyBackground: "#FFFFFF", alternateRowBackground: "#EEF5FB", bodyTextColor: "#26394A", borderColor: "#B8D0E6", accentColor: "#E3B341", totalBackground: "#245680", totalTextColor: "#FFFFFF", fontFamily: "humanist", density: "compact", bandedRows: true, emphasizeFirstColumn: true }) },
  { id: "excel-blue", name: "商务蓝", sourceLabel: "Excel · 中等色", progressColors: ["#4E86C6", "#AFCBED"], style: style({ templateId: "excel-blue", headerBackground: "#356B9B", headerTextColor: "#FFFFFF", headerBorderColor: "#8DB0CF", bodyBackground: "#FFFFFF", alternateRowBackground: "#F1F6FA", bodyTextColor: "#2D3C49", borderColor: "#D2E0EA", accentColor: "#4E86C6", totalBackground: "#DDEAF4", totalTextColor: "#294F70", fontFamily: "system", density: "comfortable", bandedRows: true, emphasizeFirstColumn: false }) },
  { id: "excel-teal", name: "青黛", sourceLabel: "Excel · 青色", progressColors: ["#3E9B91", "#BFE1DD"], style: style({ templateId: "excel-teal", headerBackground: "#286C68", headerTextColor: "#FFFFFF", headerBorderColor: "#7FB2AE", bodyBackground: "#FFFFFF", alternateRowBackground: "#EDF7F5", bodyTextColor: "#29413F", borderColor: "#CAE1DE", accentColor: "#3E9B91", totalBackground: "#D8ECE9", totalTextColor: "#245854", fontFamily: "humanist", density: "comfortable", bandedRows: true, emphasizeFirstColumn: true }) },
  { id: "excel-green", name: "松柏", sourceLabel: "Excel · 绿色", progressColors: ["#5C9A6E", "#C9E3D1"], style: style({ templateId: "excel-green", headerBackground: "#3F6F50", headerTextColor: "#FFFFFF", headerBorderColor: "#92B49D", bodyBackground: "#FFFFFF", alternateRowBackground: "#F1F7F3", bodyTextColor: "#304039", borderColor: "#D2E1D7", accentColor: "#67A178", totalBackground: "#DDEADF", totalTextColor: "#31583D", fontFamily: "serif", density: "comfortable", bandedRows: true, emphasizeFirstColumn: false }) },
  { id: "excel-gold", name: "暖金", sourceLabel: "Excel · 暖色", progressColors: ["#C99B43", "#F1DEB4"], style: style({ templateId: "excel-gold", headerBackground: "#735C34", headerTextColor: "#FFF9ED", headerBorderColor: "#BCA77C", bodyBackground: "#FFFDF8", alternateRowBackground: "#F8F2E6", bodyTextColor: "#443B2E", borderColor: "#E5D8BD", accentColor: "#C99B43", totalBackground: "#EFE1C4", totalTextColor: "#655027", fontFamily: "serif", density: "compact", bandedRows: true, emphasizeFirstColumn: true }) },
  { id: "tabulator-modern", name: "现代石墨", sourceLabel: "GitHub · Tabulator", progressColors: ["#647B8C", "#C7D3DC"], style: style({ templateId: "tabulator-modern", headerBackground: "#354550", headerTextColor: "#F7FAFC", headerBorderColor: "#697985", bodyBackground: "#FFFFFF", alternateRowBackground: "#F4F6F7", bodyTextColor: "#2F383E", borderColor: "#D8DEE2", accentColor: "#5E7D91", totalBackground: "#E6EBEE", totalTextColor: "#354550", fontFamily: "system", density: "compact", bandedRows: true, emphasizeFirstColumn: false }) },
  { id: "tabulator-simple", name: "极简灰", sourceLabel: "GitHub · Tabulator", progressColors: ["#8797A2", "#D4DCE1"], style: style({ templateId: "tabulator-simple", headerBackground: "#EEF1F3", headerTextColor: "#3D4A52", headerBorderColor: "#CBD2D7", bodyBackground: "#FFFFFF", alternateRowBackground: "#FFFFFF", bodyTextColor: "#30383D", borderColor: "#E3E7E9", accentColor: "#6F8796", totalBackground: "#F0F3F4", totalTextColor: "#3D4A52", fontFamily: "system", density: "comfortable", bandedRows: false, emphasizeFirstColumn: false }) },
  { id: "handsontable-main", name: "清朗", sourceLabel: "GitHub · Handsontable", progressColors: ["#4A8F7A", "#C5DDD6"], style: style({ templateId: "handsontable-main", headerBackground: "#F3F6F5", headerTextColor: "#30423C", headerBorderColor: "#CCD7D3", bodyBackground: "#FFFFFF", alternateRowBackground: "#F7FAF9", bodyTextColor: "#2E3935", borderColor: "#DEE5E2", accentColor: "#4A8F7A", totalBackground: "#E7F0ED", totalTextColor: "#315C4E", fontFamily: "humanist", density: "comfortable", bandedRows: true, emphasizeFirstColumn: true }) },
  { id: "handsontable-horizon", name: "云际", sourceLabel: "GitHub · Handsontable", progressColors: ["#6789B6", "#D2DEEE"], style: style({ templateId: "handsontable-horizon", headerBackground: "#E9EEF5", headerTextColor: "#334A68", headerBorderColor: "#BCC9DA", bodyBackground: "#FFFFFF", alternateRowBackground: "#F7F9FC", bodyTextColor: "#34404F", borderColor: "#E2E7EF", accentColor: "#6789B6", totalBackground: "#DFE7F1", totalTextColor: "#324B6C", fontFamily: "system", density: "comfortable", bandedRows: true, emphasizeFirstColumn: false }) },
  { id: "datatables-slate", name: "金融铅灰", sourceLabel: "GitHub · DataTables", progressColors: ["#526D82", "#C9D5DE"], style: style({ templateId: "datatables-slate", headerBackground: "#4A5965", headerTextColor: "#FFFFFF", headerBorderColor: "#788691", bodyBackground: "#FFFFFF", alternateRowBackground: "#F3F5F7", bodyTextColor: "#303A42", borderColor: "#D7DDE1", accentColor: "#5B788D", totalBackground: "#DDE3E7", totalTextColor: "#374955", fontFamily: "mono", density: "compact", bandedRows: true, emphasizeFirstColumn: false }) },
];

export type CustomTableTemplate = {
  version: 1;
  id: string;
  name: string;
  createdAt: string;
  sourceMetricFields: string[];
  sourceDimensionFields: string[];
  fieldLabels: Record<string, string>;
  tableStyle: VisualizationTableStyleConfig;
  metricRankings: VisualizationMetricRankConfig[];
  metricFormats: VisualizationMetricFormatConfig[];
  metricProgress: VisualizationMetricProgressConfig[];
  calculatedColumns: VisualizationCalculatedColumnConfig[];
  mergedDimensionFields: string[];
  frozenColumnFields: string[];
  previewProgressColors?: readonly [string, string];
};

export const bankPerformanceTemplateId = "featured-bank-performance-ranking";

const bankPerformanceTableStyle = style({
  templateId: bankPerformanceTemplateId,
  headerBackground: "#245680",
  headerTextColor: "#FFFFFF",
  headerBorderColor: "#8EB6D8",
  bodyBackground: "#FFFFFF",
  alternateRowBackground: "#EEF5FB",
  bodyTextColor: "#26394A",
  borderColor: "#B8D0E6",
  accentColor: "#244F79",
  totalBackground: "#245680",
  totalTextColor: "#FFFFFF",
  fontFamily: "humanist",
  density: "compact",
  bandedRows: true,
  emphasizeFirstColumn: true,
});

const rankingMetricLabelExcluded = /人数|人员|机构类型|类型|名称|日期|时间|环比|同比|增幅|变动|动能|比例|占比|率|目标/i;

export function createBankPerformanceTableTemplate(metricFields: string[], dimensionFields: string[], fieldLabels: Record<string, string>): CustomTableTemplate {
  const rankedMetrics = metricFields.filter((field) => !rankingMetricLabelExcluded.test(`${field} ${fieldLabels[field] || ""}`));
  const performanceMetrics = rankedMetrics.length ? rankedMetrics : metricFields.slice(0, 1);
  const labels = Object.fromEntries([...metricFields, ...dimensionFields].map((field) => [field, String(fieldLabels[field] || field).slice(0, 120)]));
  return {
    version: 1,
    id: bankPerformanceTemplateId,
    name: "银行经营排名",
    createdAt: new Date(0).toISOString(),
    sourceMetricFields: [...metricFields],
    sourceDimensionFields: [...dimensionFields],
    fieldLabels: labels,
    tableStyle: bankPerformanceTableStyle,
    metricRankings: performanceMetrics.map((metricField) => ({ metricField, direction: "desc" })),
    metricFormats: [],
    metricProgress: performanceMetrics.map((metricField) => ({
      metricField,
      denominatorMode: "column_max",
      denominatorRules: [],
      color: /综合|得分|评分/i.test(`${metricField} ${fieldLabels[metricField] || ""}`) ? "#75A94F" : "#5A9BD5",
      colorEnd: /综合|得分|评分/i.test(`${metricField} ${fieldLabels[metricField] || ""}`) ? "#DCECCF" : "#D7E8F6",
      colorMode: "gradient",
      associationRules: [],
    })),
    calculatedColumns: [],
    mergedDimensionFields: [],
    frozenColumnFields: [],
    previewProgressColors: ["#5A9BD5", "#D7E8F6"],
  };
}

export const tableTemplateStorageKey = (tenantId: string, userId: string) => `sda:table-templates:v1:${tenantId}:${userId}`;
export const tableTemplateChangedEvent = "sda:table-templates-changed";

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

export function createCustomTableTemplate(name: string, config: VisualizationCardConfig, fieldLabels: Record<string, string>): CustomTableTemplate {
  const sourceMetricFields = [...config.metricFields];
  const sourceDimensionFields = [...config.dimensionFields];
  const used = new Set([...sourceMetricFields, ...sourceDimensionFields]);
  const id = `custom-table-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return {
    version: 1,
    id,
    name: String(name || "自定义表格").trim().slice(0, 60) || "自定义表格",
    createdAt: new Date().toISOString(),
    sourceMetricFields,
    sourceDimensionFields,
    fieldLabels: Object.fromEntries(Object.entries(fieldLabels).filter(([field]) => used.has(field)).map(([field, label]) => [field, String(label || field).slice(0, 120)])),
    tableStyle: normalizeVisualizationTableStyle({ ...config.tableStyle, templateId: id }),
    metricRankings: clone(normalizeMetricRankings(config.metricRankings || [], sourceMetricFields)),
    metricFormats: clone(normalizeMetricFormats(config.metricFormats || [], sourceMetricFields)),
    metricProgress: clone(normalizeMetricProgress(config.metricProgress || [], sourceMetricFields)),
    calculatedColumns: clone(normalizeCalculatedColumns(config.calculatedColumns || [])),
    mergedDimensionFields: (config.mergedDimensionFields || []).filter((field) => sourceDimensionFields.includes(field)),
    frozenColumnFields: (config.frozenColumnFields || []).filter((field) => used.has(field)),
  };
}

export function normalizeCustomTableTemplates(value: unknown): CustomTableTemplate[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  return value.slice(0, 20).flatMap((raw): CustomTableTemplate[] => {
    if (!raw || typeof raw !== "object") return [];
    const source = raw as Partial<CustomTableTemplate>;
    const id = String(source.id || "").trim().slice(0, 160);
    if (!id || seen.has(id)) return [];
    seen.add(id);
    const sourceMetricFields = Array.isArray(source.sourceMetricFields) ? source.sourceMetricFields.map(String).filter(Boolean).slice(0, 100) : [];
    const sourceDimensionFields = Array.isArray(source.sourceDimensionFields) ? source.sourceDimensionFields.map(String).filter(Boolean).slice(0, 100) : [];
    const labels = source.fieldLabels && typeof source.fieldLabels === "object" ? Object.fromEntries(Object.entries(source.fieldLabels).slice(0, 200).map(([field, label]) => [field.slice(0, 300), String(label || field).slice(0, 120)])) : {};
    return [{
      version: 1,
      id,
      name: String(source.name || "自定义表格").trim().slice(0, 60) || "自定义表格",
      createdAt: /^\d{4}-\d{2}-\d{2}T/.test(String(source.createdAt || "")) ? String(source.createdAt) : new Date(0).toISOString(),
      sourceMetricFields,
      sourceDimensionFields,
      fieldLabels: labels,
      tableStyle: normalizeVisualizationTableStyle(source.tableStyle),
      metricRankings: normalizeMetricRankings(source.metricRankings || [], sourceMetricFields),
      metricFormats: normalizeMetricFormats(source.metricFormats || [], sourceMetricFields),
      metricProgress: normalizeMetricProgress(source.metricProgress || [], sourceMetricFields),
      calculatedColumns: normalizeCalculatedColumns(source.calculatedColumns || []),
      mergedDimensionFields: Array.isArray(source.mergedDimensionFields) ? source.mergedDimensionFields.map(String).filter((field) => sourceDimensionFields.includes(field)) : [],
      frozenColumnFields: Array.isArray(source.frozenColumnFields) ? source.frozenColumnFields.map(String).filter((field) => sourceMetricFields.includes(field) || sourceDimensionFields.includes(field)) : [],
      ...(Array.isArray(source.previewProgressColors) && source.previewProgressColors.length >= 2 ? { previewProgressColors: [String(source.previewProgressColors[0]), String(source.previewProgressColors[1])] as const } : {}),
    }];
  });
}

export function readCustomTableTemplates(key: string): CustomTableTemplate[] {
  if (typeof window === "undefined") return [];
  try { return normalizeCustomTableTemplates(JSON.parse(window.localStorage.getItem(key) || "[]")); } catch { return []; }
}

export function writeCustomTableTemplates(key: string, templates: CustomTableTemplate[]) {
  const bounded = normalizeCustomTableTemplates(templates).slice(0, 20);
  if (typeof window !== "undefined") {
    window.localStorage.setItem(key, JSON.stringify(bounded));
    window.dispatchEvent(new CustomEvent(tableTemplateChangedEvent, { detail: { key, templates: bounded } }));
  }
  return bounded;
}

type TableTemplateApplication = Pick<VisualizationCardConfig, "tableStyle" | "metricRankings" | "metricFormats" | "metricProgress" | "calculatedColumns" | "mergedDimensionFields" | "frozenColumnFields"> & { warnings: string[] };

export function applyCustomTableTemplate(template: CustomTableTemplate, metricFields: string[], dimensionFields: string[], currentLabels: Record<string, string>): TableTemplateApplication {
  const warnings: string[] = [];
  const allCurrent = [...metricFields, ...dimensionFields];
  const currentLabelCounts = new Map<string, number>();
  allCurrent.forEach((field) => { const label = String(currentLabels[field] || field); currentLabelCounts.set(label, (currentLabelCounts.get(label) || 0) + 1); });
  const mapField = (field: string, allowed: string[]) => {
    if (allowed.includes(field)) return field;
    const label = String(template.fieldLabels[field] || field);
    return currentLabelCounts.get(label) === 1 ? allowed.find((candidate) => String(currentLabels[candidate] || candidate) === label) || null : null;
  };
  const fieldMap = new Map<string, string>();
  template.sourceMetricFields.forEach((field) => { const mapped = mapField(field, metricFields); if (mapped) fieldMap.set(field, mapped); });
  template.sourceDimensionFields.forEach((field) => { const mapped = mapField(field, dimensionFields); if (mapped) fieldMap.set(field, mapped); });
  const mapExpression = (expression: string) => expression.replace(/\[([^\]]+)\]/g, (token, fieldOrLabel: string) => {
    const sourceField = [...template.sourceMetricFields].find((field) => field === fieldOrLabel || template.fieldLabels[field] === fieldOrLabel);
    if (!sourceField) return token;
    const target = fieldMap.get(sourceField);
    return target ? `[${currentLabels[target] || target}]` : token;
  });

  const metricRankings = template.metricRankings.flatMap((ranking) => {
    const metricField = fieldMap.get(ranking.metricField);
    if (!metricField) { warnings.push(`排名指标“${template.fieldLabels[ranking.metricField] || ranking.metricField}”未匹配`); return []; }
    return [{ ...ranking, metricField }];
  });
  const metricFormats = template.metricFormats.flatMap((format) => {
    const metricField = fieldMap.get(format.metricField);
    if (!metricField) { warnings.push(`格式指标“${template.fieldLabels[format.metricField] || format.metricField}”未匹配`); return []; }
    return [{ ...format, metricField }];
  });
  const metricProgress = template.metricProgress.flatMap((progress) => {
    const metricField = fieldMap.get(progress.metricField);
    const denominatorRules = progress.denominatorRules.flatMap((rule) => {
      const field = fieldMap.get(rule.field);
      return field ? [{ ...rule, field }] : [];
    });
    if (!metricField || denominatorRules.length !== progress.denominatorRules.length) { warnings.push(`进度规则“${template.fieldLabels[progress.metricField] || progress.metricField}”未完整匹配`); return []; }
    const associationRules = progress.associationRules.flatMap((rule) => {
      const targetField = fieldMap.get(rule.targetField);
      return targetField ? [{ ...rule, targetField }] : [];
    });
    return [{ ...progress, metricField, denominatorRules, associationRules }];
  });
  const calculatedColumns = template.calculatedColumns.flatMap((column) => {
    const expression = mapExpression(column.expression);
    if (expression && compileVisualizationFormula(expression, metricFields, currentLabels).error) { warnings.push(`计算列“${column.name}”未匹配`); return []; }
    return [{ ...column, expression }];
  });
  const mergedDimensionFields = template.mergedDimensionFields.flatMap((field) => fieldMap.get(field) || []);
  const frozenColumnFields = template.frozenColumnFields.flatMap((field) => fieldMap.get(field) || []);
  return {
    tableStyle: normalizeVisualizationTableStyle({ ...template.tableStyle, templateId: template.id }),
    metricRankings: normalizeMetricRankings(metricRankings, metricFields),
    metricFormats: normalizeMetricFormats(metricFormats, metricFields),
    metricProgress: normalizeMetricProgress(metricProgress, metricFields),
    calculatedColumns: normalizeCalculatedColumns(calculatedColumns),
    mergedDimensionFields,
    frozenColumnFields,
    warnings,
  };
}
