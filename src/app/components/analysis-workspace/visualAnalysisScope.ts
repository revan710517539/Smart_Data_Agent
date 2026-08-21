export const MAX_VISUAL_ANALYSIS_SOURCES = 12;
export const MAX_VISUAL_SOURCE_ROWS = 200;

export type VisualAnalysisSource = {
  id: string;
  label: string;
  group?: string;
  tables?: Array<Record<string, unknown>>;
  analysis_task_id?: string;
  question?: string;
  summary?: string;
  rows?: Array<Record<string, unknown>>;
};

export function boundedVisualRows(rows: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(rows)) return [];
  const out: Array<Record<string, unknown>> = [];
  for (const row of rows.slice(0, MAX_VISUAL_SOURCE_ROWS)) {
    if (!row || typeof row !== "object" || Array.isArray(row)) continue;
    const record = row as Record<string, unknown>;
    const raw = record.raw;
    out.push(raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Record<string, unknown> : record);
  }
  return out;
}

export function uniqueVisualSourceTables(sources: VisualAnalysisSource[]) {
  const seen = new Set<string>();
  const tables: Array<Record<string, unknown>> = [];
  for (const source of sources) {
    for (const table of source.tables || []) {
      const id = String(table.id || table.code || "").trim();
      if (!id || seen.has(id)) continue;
      seen.add(id);
      tables.push(table);
    }
  }
  return tables;
}

export function normalizeVisualAnalysisSources(sources: VisualAnalysisSource[]) {
  return sources.slice(0, MAX_VISUAL_ANALYSIS_SOURCES).map((source) => ({
    id: source.id,
    label: source.label,
    group: source.group || "",
    tables: source.tables || [],
    analysis_task_id: source.analysis_task_id || "",
    question: source.question || "",
    summary: source.summary || "",
    rows: boundedVisualRows(source.rows),
  }));
}

export function pageVisualAnalysisContext(sources: VisualAnalysisSource[], extra: Record<string, unknown> = {}) {
  const normalized = normalizeVisualAnalysisSources(sources);
  const tables = uniqueVisualSourceTables(normalized);
  return {
    ...extra,
    visual_analysis_sources: normalized,
    ...(tables.length ? { selected_data_tables: tables } : {}),
  };
}

export function mergeVisualAnalysisSourceGroups(
  existing: unknown,
  group: string,
  sources: VisualAnalysisSource[],
): VisualAnalysisSource[] {
  const current = Array.isArray(existing)
    ? existing.filter((item): item is VisualAnalysisSource => Boolean(item) && typeof item === "object" && !Array.isArray(item) && String((item as VisualAnalysisSource).group || "") !== group)
    : [];
  return normalizeVisualAnalysisSources([
    ...current,
    ...sources.map((source) => ({ ...source, group })),
  ]);
}
