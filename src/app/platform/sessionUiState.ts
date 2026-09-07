const analysisConversationSessionStoragePrefix = "smart_data_agent_self_analysis_session_v1:";
const analysisConversationStoragePrefix = "smart_data_agent_self_analysis_conversation_v1:";

export const transientUiSessionStoragePrefixes = [
  "sda:self-analysis:workbench:v1:",
  "sda:visual-card:v1:",
  "sda:visual-card:v2:",
  "sda:visual-card:v3:",
  "smart-data-agent:pending-analysis:",
  "sda:analysis-workspace:active-thread:v1:",
  analysisConversationSessionStoragePrefix,
] as const;

/**
 * Starts a clean presentation session without deleting governed business data.
 * Same-login route changes can still restore bounded UI state; logout/login cannot.
 */
export function resetTransientUiStateForNewAuthSession() {
  if (typeof window === "undefined") return;

  const conversationSessionIds = new Set<string>();
  let sessionKeys: string[] = [];
  try {
    sessionKeys = storageKeys(window.sessionStorage);
  } catch {
    // Browser storage availability must never block authentication.
  }

  for (const key of sessionKeys) {
    if (key.startsWith(analysisConversationSessionStoragePrefix)) {
      try {
        const sessionId = window.sessionStorage.getItem(key)?.trim();
        if (sessionId) conversationSessionIds.add(sessionId);
      } catch {
        // Continue resetting the remaining independent UI keys.
      }
    }
    if (!transientUiSessionStoragePrefixes.some((prefix) => key.startsWith(prefix))) continue;
    try {
      window.sessionStorage.removeItem(key);
    } catch {
      // A single unavailable key must not block login or the remaining cleanup.
    }
  }

  if (!conversationSessionIds.size) return;
  let localKeys: string[] = [];
  try {
    localKeys = storageKeys(window.localStorage);
  } catch {
    return;
  }
  for (const key of localKeys) {
    if (!key.startsWith(analysisConversationStoragePrefix)) continue;
    const belongsToClosingSession = Array.from(conversationSessionIds)
      .some((sessionId) => key.endsWith(`:${sessionId}`));
    if (!belongsToClosingSession) continue;
    try {
      window.localStorage.removeItem(key);
    } catch {
      // The new session still receives a fresh session id even if cleanup fails.
    }
  }
}

function storageKeys(storage: Storage) {
  const keys: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (key) keys.push(key);
  }
  return keys;
}
