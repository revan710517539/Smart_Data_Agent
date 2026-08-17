import type { RawField } from "../services/dataAssetApi";

export type FieldSemanticRole = "metric" | "dimension" | "date";
export type FieldDisplayMetadata = Pick<RawField, "type" | "semanticRole" | "dateFormat" | "isPrimaryKey" | "isMetric" | "isTime">;

export const metricFieldTypes = ["integer", "rate", "decimal"] as const;
export const dateFieldFormat = "yyyy-MM-dd" as const;

const metricTypes = new Set<string>(metricFieldTypes);
const dateTypes = new Set(["date", "datetime"]);

export function inferFieldSemanticRole(field: RawField): FieldSemanticRole {
  if (field.semanticRole === "metric" || field.semanticRole === "dimension" || field.semanticRole === "date") return field.semanticRole;
  if (field.isTime || dateTypes.has(field.type.toLowerCase()) || /日期|时间|date|time/i.test(`${field.fieldNameEn} ${field.fieldNameCn}`)) return "date";
  if (field.isMetric || metricTypes.has(field.type.toLowerCase())) return "metric";
  return "dimension";
}

export function inferMetricFieldType(field: RawField): (typeof metricFieldTypes)[number] {
  const current = field.type.toLowerCase();
  if (field.semanticRole === "metric" && metricTypes.has(current)) return current as (typeof metricFieldTypes)[number];
  if (/率|占比|比例|rate|ratio|percent|pct/i.test(`${field.fieldNameEn} ${field.fieldNameCn}`)) return "rate";
  if (metricTypes.has(current)) return current as (typeof metricFieldTypes)[number];
  return current === "integer" ? "integer" : "decimal";
}

export function normalizeFieldSemantics(fields: RawField[], preferredPrimaryKeys: string[] = []): RawField[] {
  if (!fields.length) return [];
  const preferred = new Set(preferredPrimaryKeys.filter(Boolean));
  let normalized = fields.map((field) => {
    const semanticRole = inferFieldSemanticRole(field);
    const type = semanticRole === "dimension" ? "string" : semanticRole === "date" ? "date" : inferMetricFieldType(field);
    return {
      ...field,
      type,
      semanticRole,
      dateFormat: semanticRole === "date" ? dateFieldFormat : undefined,
      isTime: semanticRole === "date",
      isMetric: semanticRole === "metric",
      isPrimaryKey: semanticRole === "dimension" && Boolean(field.isPrimaryKey || preferred.has(field.fieldNameEn)),
    } satisfies RawField;
  });
  if (!normalized.some((field) => field.isPrimaryKey)) {
    let index = normalized.findIndex((field) => field.semanticRole === "dimension");
    if (index < 0) index = 0;
    normalized = normalized.map((field, fieldIndex) => fieldIndex === index
      ? { ...field, semanticRole: "dimension", type: "string", dateFormat: undefined, isTime: false, isMetric: false, isPrimaryKey: true }
      : field);
  }
  return normalized;
}

export function updateFieldSemanticValue(
  fields: RawField[],
  index: number,
  key: "semanticRole" | "type" | "isPrimaryKey" | "explanation" | "exampleUsage",
  value: string | boolean,
) {
  const updated = fields.map((field, fieldIndex) => {
    if (fieldIndex !== index) return field;
    if (key === "semanticRole") {
      const semanticRole = value as FieldSemanticRole;
      return {
        ...field,
        semanticRole,
        type: semanticRole === "dimension" ? "string" : semanticRole === "date" ? "date" : inferMetricFieldType(field),
        dateFormat: semanticRole === "date" ? dateFieldFormat : undefined,
        isTime: semanticRole === "date",
        isMetric: semanticRole === "metric",
        isPrimaryKey: semanticRole === "dimension" ? field.isPrimaryKey : false,
      };
    }
    if (key === "isPrimaryKey") {
      return value
        ? { ...field, semanticRole: "dimension" as const, type: "string", dateFormat: undefined, isTime: false, isMetric: false, isPrimaryKey: true }
        : { ...field, isPrimaryKey: false };
    }
    return { ...field, [key]: value };
  });
  return normalizeFieldSemantics(updated);
}

export function primaryKeyFields(fields: RawField[]) {
  return normalizeFieldSemantics(fields).filter((field) => field.isPrimaryKey).map((field) => field.fieldNameEn);
}

export function fieldMetadataMap(fields: RawField[]): Record<string, FieldDisplayMetadata> {
  return Object.fromEntries(normalizeFieldSemantics(fields).map((field) => [field.fieldNameEn, {
    type: field.type,
    semanticRole: field.semanticRole,
    dateFormat: field.dateFormat,
    isPrimaryKey: field.isPrimaryKey,
    isMetric: field.isMetric,
    isTime: field.isTime,
  }]));
}

export function formatFieldValue(value: unknown, metadata?: FieldDisplayMetadata) {
  if (value === null || value === undefined || value === "") return "—";
  if (metadata?.semanticRole === "date" || dateTypes.has(String(metadata?.type || "").toLowerCase())) {
    const text = String(value);
    const match = text.match(/^(\d{4}-\d{2}-\d{2})/);
    return match?.[1] || text;
  }
  const type = String(metadata?.type || "").toLowerCase();
  if (type === "integer" || type === "decimal" || type === "rate") {
    const number = typeof value === "number" ? value : Number(String(value).replace(/,/g, ""));
    if (Number.isFinite(number)) {
      const formatted = number.toLocaleString("zh-CN", type === "integer"
        ? { maximumFractionDigits: 0 }
        : { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      return type === "rate" ? `${formatted}%` : formatted;
    }
  }
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
