import { useEffect, useRef } from "react";
import type { TopicTableAsset } from "../../services/dataAssetApi";
import type { AnalysisDataTableSelection, AnalysisRow, ResultMode, ResultVisualKey, VisualizationType } from "./domain";

export type SelfAnalysisWorkbenchSnapshot = {
  selectedDataTables: AnalysisDataTableSelection[];
  selectedTopic: TopicTableAsset | null;
  showResult: boolean;
  analysisPlan: string;
  analysisRows: AnalysisRow[];
  analysisSummary: string;
  analysisScenarios: string;
  analysisTaskId: string;
  resultMode: ResultMode;
  visualTypes: Record<ResultVisualKey, VisualizationType>;
  scriptPlanName: string;
  sqlScript: string;
  pythonScript: string;
  analysisInputCollapsed: boolean;
};

function selfAnalysisWorkbenchStorageKey(tenantId: string, userId: string) {
  return `sda:self-analysis:workbench:v1:${tenantId}:${userId}`;
}

export function clearSelfAnalysisWorkbenchPersistence(tenantId: string, userId: string) {
  try { sessionStorage.removeItem(selfAnalysisWorkbenchStorageKey(tenantId, userId)); } catch { /* storage failure must not block an explicit restore */ }
}

export function useSelfAnalysisWorkbenchPersistence({ tenantId, userId, enabled, state, restore }: { tenantId: string; userId: string; enabled: boolean; state: SelfAnalysisWorkbenchSnapshot; restore: (snapshot: SelfAnalysisWorkbenchSnapshot) => void }) {
  const key = selfAnalysisWorkbenchStorageKey(tenantId, userId);
  const hydratedKeyRef = useRef("");
  const skipSaveRef = useRef(false);
  const restoreRef = useRef(restore);
  restoreRef.current = restore;

  useEffect(() => {
    if (!enabled || hydratedKeyRef.current === key) return;
    try {
      const parsed = JSON.parse(sessionStorage.getItem(key) || "null") as SelfAnalysisWorkbenchSnapshot | null;
      if (parsed && Array.isArray(parsed.selectedDataTables) && Array.isArray(parsed.analysisRows) && parsed.visualTypes?.primary && parsed.visualTypes?.secondary) {
        skipSaveRef.current = true;
        restoreRef.current(parsed);
      }
    } catch { /* invalid session state closes to the current empty workbench */ }
    hydratedKeyRef.current = key;
  }, [enabled, key]);

  useEffect(() => {
    if (!enabled || hydratedKeyRef.current !== key) return;
    if (skipSaveRef.current) { skipSaveRef.current = false; return; }
    const bounded = { ...state, analysisRows: state.analysisRows.slice(0, 200) };
    try { sessionStorage.setItem(key, JSON.stringify(bounded)); } catch { /* session quota must not block analysis */ }
  }, [enabled, key, state]);
}
