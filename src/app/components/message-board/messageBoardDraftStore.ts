export type StoredMessageBoardDraftImage = {
  name: string;
  type: string;
  lastModified: number;
  blob: Blob;
};

export type StoredMessageBoardDraft = {
  content: string;
  images: StoredMessageBoardDraftImage[];
  updatedAt: string;
};

const databaseName = "smart-data-agent-message-board";
const storeName = "page-drafts";
const fallbackPrefix = "smart-data-agent:message-board-draft:";

export function messageBoardDraftKey(tenantId: string, userId: string, pageKey: string) {
  return `${tenantId}:${userId}:${pageKey}`;
}

export async function loadMessageBoardDraft(key: string): Promise<StoredMessageBoardDraft | null> {
  if (!supportsIndexedDb()) return loadFallbackDraft(key);
  try {
    const database = await openDraftDatabase();
    return await requestResult<StoredMessageBoardDraft | undefined>(database.transaction(storeName, "readonly").objectStore(storeName).get(key)) || null;
  } catch {
    return loadFallbackDraft(key);
  }
}

export async function saveMessageBoardDraft(key: string, draft: StoredMessageBoardDraft) {
  saveFallbackDraft(key, draft);
  if (!supportsIndexedDb()) return;
  const database = await openDraftDatabase();
  await transactionComplete(database.transaction(storeName, "readwrite"), (store) => store.put(draft, key));
}

export async function clearMessageBoardDraft(key: string) {
  if (typeof window !== "undefined") window.localStorage.removeItem(`${fallbackPrefix}${key}`);
  if (!supportsIndexedDb()) return;
  const database = await openDraftDatabase();
  await transactionComplete(database.transaction(storeName, "readwrite"), (store) => store.delete(key));
}

function supportsIndexedDb() {
  return typeof indexedDB !== "undefined";
}

function openDraftDatabase() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(databaseName, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(storeName)) request.result.createObjectStore(storeName);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("留言草稿存储不可用"));
  });
}

function requestResult<T>(request: IDBRequest<T>) {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("留言草稿读取失败"));
  });
}

function transactionComplete(transaction: IDBTransaction, action: (store: IDBObjectStore) => IDBRequest) {
  return new Promise<void>((resolve, reject) => {
    action(transaction.objectStore(storeName));
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error || new Error("留言草稿保存失败"));
    transaction.onabort = () => reject(transaction.error || new Error("留言草稿保存已取消"));
  });
}

function loadFallbackDraft(key: string): StoredMessageBoardDraft | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(`${fallbackPrefix}${key}`);
    const parsed = raw ? JSON.parse(raw) as Partial<StoredMessageBoardDraft> : null;
    if (!parsed || typeof parsed.content !== "string") return null;
    return { content: parsed.content, images: [], updatedAt: String(parsed.updatedAt || "") };
  } catch {
    return null;
  }
}

function saveFallbackDraft(key: string, draft: StoredMessageBoardDraft) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(`${fallbackPrefix}${key}`, JSON.stringify({ content: draft.content, updatedAt: draft.updatedAt }));
  } catch {
    // IndexedDB remains authoritative when localStorage is unavailable or full.
  }
}
