import type { AnalysisDataTableSelection } from "./domain";

export type PendingAnalysisRun = {
  runId: string;
  question: string;
  selectedDataTables: AnalysisDataTableSelection[];
  startedAt: string;
};

function storageKey(tenantId: string, userId: string) {
  return `smart-data-agent:pending-analysis:${encodeURIComponent(tenantId)}:${encodeURIComponent(userId)}`;
}

export function savePendingAnalysisRun(tenantId: string, userId: string, pending: PendingAnalysisRun) {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(storageKey(tenantId, userId), JSON.stringify(pending));
}

export function loadPendingAnalysisRun(tenantId: string, userId: string): PendingAnalysisRun | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(storageKey(tenantId, userId));
    const value = raw ? JSON.parse(raw) as Partial<PendingAnalysisRun> : null;
    if (!value?.runId || !value.question || !value.startedAt) return null;
    if (Date.now() - Date.parse(value.startedAt) > 16 * 60 * 1000) {
      window.sessionStorage.removeItem(storageKey(tenantId, userId));
      return null;
    }
    return {
      runId: value.runId,
      question: value.question,
      selectedDataTables: Array.isArray(value.selectedDataTables) ? value.selectedDataTables : [],
      startedAt: value.startedAt,
    };
  } catch {
    return null;
  }
}

export function clearPendingAnalysisRun(tenantId: string, userId: string, runId?: string) {
  if (typeof window === "undefined") return;
  if (runId) {
    const pending = loadPendingAnalysisRun(tenantId, userId);
    if (pending && pending.runId !== runId) return;
  }
  window.sessionStorage.removeItem(storageKey(tenantId, userId));
}

export function isAnalysisNavigationAbort(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}
