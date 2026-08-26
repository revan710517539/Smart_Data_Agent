import type { PageDataAsset, PageDataRows, RawField, RawTableAsset, TopicDataSnapshot, TopicTableAsset } from "../../services/dataAssetApi";
import type { VisualReportDatasetReference } from "../../services/visualReportApi";
import { analysisTableLogicalTitle, type AnalysisRow } from "../self-analysis/domain";

export type VisualReportDataset = RawTableAsset | TopicTableAsset | PageDataAsset;

export function visualReportDatasetReference(dataset: VisualReportDataset): VisualReportDatasetReference {
  if ("tableNameEn" in dataset) {
    return {
      id: dataset.id,
      kind: "raw",
      name: dataset.tableNameCn || dataset.tableNameEn,
      code: dataset.tableNameEn,
      sourceKey: dataset.sourceKey,
      schemaFingerprint: dataset.schemaFingerprint,
      fields: dataset.fields,
    };
  }
  if (isPageDataDataset(dataset)) {
    return {
      id: dataset.id,
      kind: "page_data",
      name: dataset.name || dataset.sourceTableName || "多机构页面数据",
      code: `page_data_${dataset.id}`,
      sourceKey: dataset.sourceKey,
      schemaFingerprint: dataset.schemaFingerprint,
      relationshipGroupId: dataset.relationshipGroupId,
      fields: dataset.sourceFields || [],
    };
  }
  return {
    id: dataset.id,
    kind: "topic",
    name: dataset.name,
    code: dataset.code,
    schemaFingerprint: dataset.schemaVersion,
    fields: Array.isArray(dataset.fields) ? dataset.fields : [],
  };
}

export function rowsFromRawVisualDataset(dataset: RawTableAsset): AnalysisRow[] {
  const fields = dataset.fields || [];
  const rows = Array.isArray(dataset.previewRows) ? dataset.previewRows : [];
  const projected = rows.map((source) => Object.fromEntries(fields.map((field) => [
    field.fieldNameEn,
    source[field.fieldNameEn] ?? source[field.fieldNameCn] ?? "",
  ])));
  return toVisualRows(projected, fields);
}

export function rowsFromTopicVisualDataset(dataset: TopicTableAsset, snapshot: TopicDataSnapshot): AnalysisRow[] {
  const fields = Array.isArray(dataset.fields) ? dataset.fields : inferFields(snapshot.rows);
  return toVisualRows(snapshot.rows, fields);
}

export function rowsFromPageVisualDataset(dataset: PageDataAsset, snapshot: PageDataRows): AnalysisRow[] {
  return toVisualRows(snapshot.rows, dataset.sourceFields || []);
}

export function visualReportDatasetMatches(reference: VisualReportDatasetReference, dataset: VisualReportDataset) {
  if (reference.kind === "raw" && "tableNameEn" in dataset) {
    const sameSource = reference.sourceKey && dataset.sourceKey
      ? reference.sourceKey === dataset.sourceKey
      : reference.id === dataset.id;
    if (!sameSource) return false;
    return visualReportRawSchemaCompatible(reference, dataset);
  }
  if (reference.kind === "page_data" && isPageDataDataset(dataset)) {
    return reference.id === dataset.id
      && (!reference.relationshipGroupId || reference.relationshipGroupId === dataset.relationshipGroupId)
      && (!reference.schemaFingerprint || reference.schemaFingerprint === dataset.schemaFingerprint);
  }
  return reference.kind === "topic" && reference.id === dataset.id && "code" in dataset && !("tableNameEn" in dataset);
}

export function resolveVisualReportRawTable(reference: VisualReportDatasetReference, catalog: RawTableAsset[]) {
  const rawTables = catalog.filter((item) => item && typeof item === "object");
  if (!rawTables.length) {
    return {
      dataset: undefined,
      error: "当前机构目录中找不到该原始表。可能是交付文件已下线，或已换成另一份业务表。",
    };
  }
  const bySource = uniqueRawTables(rawTables, (item) => Boolean(reference.sourceKey) && item.sourceKey === reference.sourceKey);
  const byId = uniqueRawTables(rawTables, (item) => Boolean(reference.id) && item.id === reference.id);
  const byLogicalTitle = uniqueRawTablesByLogicalTitle(rawTables, reference);
  const candidates = bySource.length ? bySource : byId.length ? byId : byLogicalTitle;
  if (candidates.length !== 1) {
    return {
      dataset: undefined,
      error: "当前机构目录中找不到该原始表。可能是交付文件已下线，或已换成另一份业务表。",
    };
  }
  const dataset = candidates[0];
  if (!visualReportRawSchemaCompatible(reference, dataset)) {
    return {
      dataset: undefined,
      error: "原始表已更新，但字段结构与当时保存的图表不兼容，已停止展示旧配置。",
    };
  }
  return { dataset, error: "" };
}

function uniqueRawTables(catalog: RawTableAsset[], predicate: (item: RawTableAsset) => boolean) {
  const matches = catalog.filter(predicate);
  return matches.length === 1 ? matches : [];
}

function uniqueRawTablesByLogicalTitle(catalog: RawTableAsset[], reference: VisualReportDatasetReference) {
  const requested = new Set(
    [reference.name, reference.code]
      .filter((value) => visualReportLogicalTitleCandidate(String(value || "")))
      .map((value) => analysisTableLogicalTitle(String(value || "")))
      .filter(Boolean),
  );
  if (!requested.size) return [];
  return uniqueRawTables(catalog, (item) => {
    const titles = [item.tableNameCn, item.tableNameEn, item.fileName, item.relativePath]
      .map((value) => analysisTableLogicalTitle(String(value || "")))
      .filter(Boolean);
    return titles.some((title) => requested.has(title));
  });
}

function visualReportLogicalTitleCandidate(value: string) {
  const title = analysisTableLogicalTitle(value);
  return Boolean(title) && !/^csv[0-9a-f]{8,}$/i.test(title);
}

function visualReportRawSchemaCompatible(reference: VisualReportDatasetReference, dataset: RawTableAsset) {
  if (!reference.schemaFingerprint || !dataset.schemaFingerprint || reference.schemaFingerprint === dataset.schemaFingerprint) {
    return true;
  }
  const storedFields = (reference.fields || []).map((field) => field.fieldNameEn).filter(Boolean);
  if (!storedFields.length) return false;
  const currentFields = new Set((dataset.fields || []).map((field) => field.fieldNameEn).filter(Boolean));
  return storedFields.every((field) => currentFields.has(field));
}

export function isPageDataDataset(dataset: VisualReportDataset): dataset is PageDataAsset {
  return "institutionScope" in dataset && "sourceFields" in dataset;
}

function toVisualRows(sourceRows: Array<Record<string, unknown>>, fields: RawField[]): AnalysisRow[] {
  const labels = Object.fromEntries(fields.map((field) => [field.fieldNameEn, field.fieldNameCn || field.fieldNameEn]));
  const fieldMetadata = Object.fromEntries(fields.map((field) => [field.fieldNameEn, {
    type: field.type,
    semanticRole: field.semanticRole,
    dateFormat: field.dateFormat,
    isPrimaryKey: field.isPrimaryKey,
  }]));
  const metricField = fields.find((field) => field.semanticRole === "metric" || field.isMetric)?.fieldNameEn
    || fields.find((field) => /int|decimal|number|float|double|rate/i.test(field.type))?.fieldNameEn
    || fields[0]?.fieldNameEn
    || "value";
  const dimensionField = fields.find((field) => field.fieldNameEn !== metricField && (field.semanticRole === "dimension" || field.semanticRole === "date" || field.isTime || field.isPrimaryKey))?.fieldNameEn
    || fields.find((field) => field.fieldNameEn !== metricField)?.fieldNameEn
    || metricField;
  return sourceRows.slice(0, 200).map((raw, index) => ({
    branch: String(raw[dimensionField] ?? `第${index + 1}行`),
    productLine: "",
    customerSegment: "",
    amount: numericValue(raw[metricField]),
    metricName: labels[metricField] || metricField,
    metricUnit: "",
    fieldLabels: labels,
    fieldMetadata,
    raw,
    completion: "—",
    conversion: "—",
    overdueRate: "—",
    weekChange: "—",
  }));
}

function inferFields(rows: Array<Record<string, string>>): RawField[] {
  const first = rows[0] || {};
  return Object.keys(first).map((field) => ({
    fieldNameEn: field,
    fieldNameCn: field,
    type: Number.isFinite(Number(first[field])) ? "decimal" : "string",
    semanticRole: Number.isFinite(Number(first[field])) ? "metric" : "dimension",
    explanation: "",
  }));
}

function numericValue(value: unknown) {
  const parsed = Number(String(value ?? "").replace(/,/g, "").replace(/%$/, ""));
  return Number.isFinite(parsed) ? parsed : 0;
}
