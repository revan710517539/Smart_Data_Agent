import { useEffect, useRef } from "react";
import { registerBeforeLogout } from "../../platform/beforeLogout";
import { apiContextHeaders } from "../../services/apiContext";
import { getApiBaseUrl } from "../../services/apiClient";
import { saveDataAssetItem } from "../../services/dataAssetApi";
import {
  buildTopicTableItem,
  canPersistTopicTable,
  TOPIC_TABLE_SKIP_PERSIST_ERRORS,
  topicTableFieldsFromRows,
  type CompletedAnalysisRound,
} from "./topicTablePrecipitation";

async function persistCompletedAnalysisRound(
  round: CompletedAnalysisRound,
  options: { keepalive?: boolean } = {},
) {
  if (!canPersistTopicTable(round) || !topicTableFieldsFromRows(round.rows).length) return "skipped";
  const item = buildTopicTableItem(round);
  if (!item.sql) return "skipped";
  if (options.keepalive) {
    const response = await fetch(`${getApiBaseUrl()}/api/data-assets/item`, {
      method: "POST",
      credentials: "include",
      keepalive: true,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...apiContextHeaders({ tenantId: round.tenantId, userId: round.userId }),
      },
      body: JSON.stringify({ item_type: "topic_table", item }),
    });
    if (response.ok || response.status === 0 || response.status === 400) return response.ok ? "saved" : "skipped";
    throw new Error(`topic_table_keepalive_${response.status}`);
  }
  try {
    await saveDataAssetItem({ tenantId: round.tenantId, userId: round.userId, itemType: "topic_table", item });
    return "saved";
  } catch (error) {
    const code = error && typeof error === "object" && "code" in error ? String(error.code) : "";
    if (TOPIC_TABLE_SKIP_PERSIST_ERRORS.has(code) || /上传文件分析默认不沉淀主题表|没有可沉淀的执行证据/.test(String(error instanceof Error ? error.message : error))) {
      return "skipped";
    }
    throw error;
  }
}

function normalizeQuestion(value: string) {
  return value.trim().replace(/\s+/g, " ");
}

export function useTopicTablePrecipitation() {
  const pendingRef = useRef<CompletedAnalysisRound | null>(null);
  const persistedIdsRef = useRef(new Set<string>());
  const inflightRef = useRef<string>("");

  const persistRound = async (round: CompletedAnalysisRound, keepalive = false) => {
    if (!canPersistTopicTable(round) || persistedIdsRef.current.has(round.taskId) || inflightRef.current === round.taskId) {
      return;
    }
    inflightRef.current = round.taskId;
    try {
      const result = await persistCompletedAnalysisRound(round, { keepalive });
      if (result === "saved" || result === "skipped") persistedIdsRef.current.add(round.taskId);
    } catch {
      /* 自动沉淀失败不得打断分析或退出 */
    } finally {
      if (inflightRef.current === round.taskId) inflightRef.current = "";
    }
  };

  const rememberCompletedRound = (round: CompletedAnalysisRound | null) => {
    if (!round || !canPersistTopicTable(round)) {
      pendingRef.current = null;
      return;
    }
    pendingRef.current = round;
  };

  const flush = async (keepalive = false) => {
    const pending = pendingRef.current;
    if (!pending) return;
    pendingRef.current = null;
    await persistRound(pending, keepalive);
  };

  const prepareQuestionSwitch = async (nextQuestion: string) => {
    const pending = pendingRef.current;
    if (!pending) return;
    if (normalizeQuestion(pending.question) === normalizeQuestion(nextQuestion)) return;
    pendingRef.current = null;
    await persistRound(pending);
  };

  useEffect(() => registerBeforeLogout(() => flush(false)), []);

  useEffect(() => {
    const onLeave = () => {
      void flush(true);
    };
    window.addEventListener("pagehide", onLeave);
    window.addEventListener("beforeunload", onLeave);
    return () => {
      window.removeEventListener("pagehide", onLeave);
      window.removeEventListener("beforeunload", onLeave);
    };
  }, []);

  return { rememberCompletedRound, prepareQuestionSwitch, flush };
}
