import { apiRequest, getApiBaseUrl } from "./apiClient";
import { apiContextHeaders } from "./apiContext";

export type MessageBoardQuote = {
  target_id?: string;
  target_type?: string;
  label?: string;
  selected_text: string;
};

export type MessageBoardEntry = {
  message_id: string;
  tenant_id: string;
  author_user_id: string;
  author_name: string;
  page_key: string;
  page_title: string;
  page_url: string;
  content: string;
  quote_context: MessageBoardQuote | Record<string, never>;
  attachment_ids: string[];
  status: "new" | "adopted" | "completed";
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  lock_version: number;
};

type Context = { tenantId: string; userId: string };

export async function fetchMessageBoard(pageKey: string, context: Context) {
  const params = new URLSearchParams({ page_key: pageKey });
  return apiRequest<{ messages: MessageBoardEntry[] }>(`/api/message-board?${params}`, { context });
}

export async function createMessageBoardEntry(
  payload: Pick<MessageBoardEntry, "message_id" | "page_key" | "page_title" | "page_url" | "content"> & {
    quote_context: MessageBoardQuote | Record<string, never>;
    attachment_ids: string[];
  },
  context: Context,
) {
  return apiRequest<{ message: MessageBoardEntry }>("/api/message-board", { method: "POST", context, body: payload });
}

export async function updateMessageBoardEntry(
  payload: Pick<MessageBoardEntry, "message_id" | "content" | "quote_context" | "attachment_ids"> & {
    expected_lock_version: number;
  },
  context: Context,
) {
  return apiRequest<{ message: MessageBoardEntry }>("/api/message-board", { method: "PUT", context, body: payload });
}

export async function archiveMessageBoardEntry(messageId: string, expectedLockVersion: number, context: Context) {
  return apiRequest<{ message: MessageBoardEntry }>("/api/message-board/archive", {
    method: "PUT",
    context,
    body: { message_id: messageId, expected_lock_version: expectedLockVersion },
  });
}

export async function deleteMessageBoardEntry(messageId: string, expectedLockVersion: number, context: Context) {
  return apiRequest<{ deleted_message_id: string }>("/api/message-board", {
    method: "DELETE",
    context,
    body: { message_id: messageId, expected_lock_version: expectedLockVersion },
  });
}

export async function updateMessageBoardStatus(
  messageId: string,
  status: MessageBoardEntry["status"],
  expectedLockVersion: number,
  context: Context,
) {
  return apiRequest<{ message: MessageBoardEntry }>("/api/message-board/admin/status", {
    method: "PUT",
    context,
    body: { message_id: messageId, status, expected_lock_version: expectedLockVersion },
  });
}

export async function uploadMessageBoardImage(file: File, messageId: string, context: Context) {
  const contentBase64 = await fileToBase64(file);
  return apiRequest<{
    status: string;
    attachment: { attachment_id: string; file_name: string };
    content_url: string;
  }>("/api/message-board/image", {
    method: "POST",
    context,
    body: { message_id: messageId, file_name: file.name || "pasted-screenshot.png", content_base64: contentBase64, classification: "internal" },
    timeoutMs: 60_000,
  });
}

export async function fetchMessageBoardAdmin(
  { query = "", page = 1, pageSize = 50 }: { query?: string; page?: number; pageSize?: number },
  context: Context,
) {
  const params = new URLSearchParams({ query, page: String(page), page_size: String(pageSize) });
  return apiRequest<{ messages: MessageBoardEntry[]; total: number; page: number; page_size: number }>(
    `/api/message-board/admin?${params}`,
    { context },
  );
}

export function messageBoardAttachmentUrl(attachmentId: string) {
  const params = new URLSearchParams({ attachment_id: attachmentId });
  return `${getApiBaseUrl()}/api/message-board/attachment?${params}`;
}

export async function fetchMessageBoardAttachment(attachmentId: string, context: Context) {
  const response = await fetch(messageBoardAttachmentUrl(attachmentId), {
    credentials: "include",
    headers: apiContextHeaders(context),
  });
  if (!response.ok) throw new Error("留言截图加载失败");
  return URL.createObjectURL(await response.blob());
}

function fileToBase64(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || "");
      const separator = value.indexOf(",");
      if (separator < 0) return reject(new Error("图片读取失败"));
      resolve(value.slice(separator + 1));
    };
    reader.onerror = () => reject(reader.error || new Error("图片读取失败"));
    reader.readAsDataURL(file);
  });
}
