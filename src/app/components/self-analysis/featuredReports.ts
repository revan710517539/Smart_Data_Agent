import { useCallback, useEffect, useState } from "react";
import { scopedStorageKey } from "./domain";

export type FeaturedReportKind = "analysis" | "visual";
export type FeaturedReportRef = { kind: FeaturedReportKind; id: string };
export type ReportKindTab = "featured" | "analysis" | "visual";

export const featuredReportsStoragePrefix = "smart_data_agent_featured_reports_v1";
export const featuredReportsChangedEvent = "smart-data-agent-featured-reports-changed";

export function featuredReportsStorageKey(tenantId: string, userId: string) {
  return scopedStorageKey(featuredReportsStoragePrefix, tenantId, userId);
}

export function featuredReportKey(ref: FeaturedReportRef) {
  return `${ref.kind}:${ref.id}`;
}

export function parseFeaturedReportRef(value: unknown): FeaturedReportRef | null {
  if (!value || typeof value !== "object") return null;
  const record = value as { kind?: unknown; id?: unknown };
  if (record.kind !== "analysis" && record.kind !== "visual") return null;
  if (typeof record.id !== "string" || !record.id.trim()) return null;
  return { kind: record.kind, id: record.id.trim() };
}

export function loadFeaturedReports(tenantId: string, userId: string): FeaturedReportRef[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(featuredReportsStorageKey(tenantId, userId));
    const parsed = raw ? JSON.parse(raw) as unknown : [];
    if (!Array.isArray(parsed)) return [];
    const seen = new Set<string>();
    const refs: FeaturedReportRef[] = [];
    for (const item of parsed) {
      const ref = parseFeaturedReportRef(item);
      if (!ref) continue;
      const key = featuredReportKey(ref);
      if (seen.has(key)) continue;
      seen.add(key);
      refs.push(ref);
    }
    return refs;
  } catch {
    return [];
  }
}

export function saveFeaturedReports(tenantId: string, userId: string, refs: FeaturedReportRef[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(featuredReportsStorageKey(tenantId, userId), JSON.stringify(refs));
  window.dispatchEvent(new CustomEvent(featuredReportsChangedEvent, { detail: { tenantId, userId, refs } }));
}

export function isFeaturedReport(refs: FeaturedReportRef[], kind: FeaturedReportKind, id: string) {
  return refs.some((ref) => ref.kind === kind && ref.id === id);
}

export function toggleFeaturedReport(refs: FeaturedReportRef[], kind: FeaturedReportKind, id: string): FeaturedReportRef[] {
  if (isFeaturedReport(refs, kind, id)) return refs.filter((ref) => !(ref.kind === kind && ref.id === id));
  return [...refs, { kind, id }];
}

export function pruneFeaturedReports(
  refs: FeaturedReportRef[],
  live: { analysisIds: Iterable<string>; visualIds: Iterable<string> },
) {
  const analysisIds = new Set(live.analysisIds);
  const visualIds = new Set(live.visualIds);
  return refs.filter((ref) => (ref.kind === "analysis" ? analysisIds.has(ref.id) : visualIds.has(ref.id)));
}

export function defaultMyReportsTab(hasFeatured: boolean): ReportKindTab {
  return hasFeatured ? "featured" : "analysis";
}

function sameFeaturedRefs(left: FeaturedReportRef[], right: FeaturedReportRef[]) {
  return left.length === right.length && left.every((ref, index) => featuredReportKey(ref) === featuredReportKey(right[index]));
}

export function useFeaturedReports(tenantId: string, userId: string) {
  const [refs, setRefs] = useState<FeaturedReportRef[]>(() => loadFeaturedReports(tenantId, userId));

  useEffect(() => {
    const reload = () => setRefs(loadFeaturedReports(tenantId, userId));
    reload();
    window.addEventListener(featuredReportsChangedEvent, reload);
    return () => window.removeEventListener(featuredReportsChangedEvent, reload);
  }, [tenantId, userId]);

  const commit = useCallback((next: FeaturedReportRef[]) => {
    saveFeaturedReports(tenantId, userId, next);
    setRefs(next);
  }, [tenantId, userId]);

  const toggle = useCallback((kind: FeaturedReportKind, id: string) => {
    commit(toggleFeaturedReport(loadFeaturedReports(tenantId, userId), kind, id));
  }, [commit, tenantId, userId]);

  const remove = useCallback((kind: FeaturedReportKind, id: string) => {
    commit(loadFeaturedReports(tenantId, userId).filter((ref) => !(ref.kind === kind && ref.id === id)));
  }, [commit, tenantId, userId]);

  const replace = useCallback((next: FeaturedReportRef[]) => {
    if (sameFeaturedRefs(loadFeaturedReports(tenantId, userId), next)) return;
    commit(next);
  }, [commit, tenantId, userId]);

  const isFeatured = useCallback((kind: FeaturedReportKind, id: string) => isFeaturedReport(refs, kind, id), [refs]);

  return { refs, isFeatured, toggle, remove, replace };
}
