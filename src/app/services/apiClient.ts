import { apiContextHeaders, hasStoredAuthSession, type ApiContextParams } from "./apiContext";

type ApiRequestOptions = Omit<RequestInit, "body" | "headers" | "signal"> & {
  body?: unknown;
  context?: ApiContextParams;
  headers?: Record<string, string>;
  timeoutMs?: number;
  readCache?: ApiReadCachePolicy | false;
};

export type ApiReadCachePolicy = {
  /** A deliberately short browser-memory TTL. Tenant APIs remain HTTP no-store. */
  ttlMs: number;
  tags?: string[];
  forceRefresh?: boolean;
};

type ApiReadCacheEntry = {
  expiresAt: number;
  payload: unknown;
  tags: string[];
};

const apiBase = (import.meta.env.VITE_ANALYSIS_API_URL || "").replace(/\/$/, "");
const apiReadCache = new Map<string, ApiReadCacheEntry>();
const apiReadInflight = new Map<string, Promise<unknown>>();
let apiReadCacheGeneration = 0;
let sessionRefreshRequest: Promise<boolean> | null = null;

export const sessionRevalidationEvent = "smart-data-agent:session-revalidation-required";

export function getApiBaseUrl() {
  return apiBase;
}

export class ApiRequestError extends Error {
  status: number;
  code: string;
  payload: unknown;

  constructor(message: string, status: number, code = "api_request_error", payload: unknown = null) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const method = String(options.method || "GET").toUpperCase();
  const policy = options.readCache;
  if (!policy || method !== "GET" || options.body !== undefined || path.startsWith("/api/auth/")) {
    const payload = await executeApiRequest<T>(path, options);
    // A successful mutation may change multiple page projections. Clearing the
    // small in-memory read cache is safer than trying to infer every consumer.
    if (method !== "GET" && method !== "HEAD") clearApiReadCache();
    return payload;
  }

  const cacheKey = apiReadCacheKey(path, options);
  const cached = apiReadCache.get(cacheKey);
  if (!policy.forceRefresh && cached && cached.expiresAt > Date.now()) {
    return cloneApiPayload(cached.payload) as T;
  }
  const existing = apiReadInflight.get(cacheKey);
  if (!policy.forceRefresh && existing) {
    return cloneApiPayload(await existing) as T;
  }
  const generation = apiReadCacheGeneration;
  let pending: Promise<T>;
  pending = executeApiRequest<T>(path, { ...options, readCache: false })
    .then((payload) => {
      if (generation === apiReadCacheGeneration) {
        apiReadCache.set(cacheKey, {
          expiresAt: Date.now() + Math.max(0, policy.ttlMs),
          payload: cloneApiPayload(payload),
          tags: [...(policy.tags || [])],
        });
      }
      return payload;
    })
    .finally(() => {
      if (apiReadInflight.get(cacheKey) === pending) apiReadInflight.delete(cacheKey);
    });
  apiReadInflight.set(cacheKey, pending);
  return cloneApiPayload(await pending) as T;
}

export function clearApiReadCache(tags?: string[]) {
  apiReadCacheGeneration += 1;
  apiReadInflight.clear();
  if (!tags?.length) {
    apiReadCache.clear();
    return;
  }
  const requested = new Set(tags);
  for (const [key, entry] of apiReadCache.entries()) {
    if (entry.tags.some((tag) => requested.has(tag))) apiReadCache.delete(key);
  }
}

async function executeApiRequest<T>(path: string, options: ApiRequestOptions): Promise<T> {
  const {
    body,
    context,
    headers = {},
    timeoutMs = 12000,
    readCache: _readCache,
    ...requestInit
  } = options;
  const hasBody = body !== undefined;
  const requestHeaders: Record<string, string> = {
    Accept: "application/json",
    // Authentication routes resolve identity from their request body or the
    // signed HttpOnly cookie. A cached tenant header can make a valid cookie
    // look unauthorized after switching local frontend ports.
    ...(path.startsWith("/api/auth/") ? {} : apiContextHeaders(context)),
    ...headers,
  };
  let requestBody: BodyInit | undefined;
  if (hasBody) {
    if (body instanceof FormData || body instanceof Blob || typeof body === "string") {
      requestBody = body;
    } else {
      requestHeaders["Content-Type"] = requestHeaders["Content-Type"] || "application/json";
      requestBody = JSON.stringify(body);
    }
  }

  let lastError: unknown = null;
  const attempts = headers["X-Startup-Retry"] === "1" ? 1 : 5;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${apiBase}${path}`, {
        ...requestInit,
        credentials: "include",
        headers: requestHeaders,
        body: requestBody,
        signal: controller.signal,
      });
      let payload: unknown;
      try {
        payload = await parseJsonPayload(response);
      } catch (error) {
        if (error instanceof ApiRequestError && error.code === "invalid_json_response" && !response.ok) {
          payload = { error: "api_unavailable", message: "Data Agent API 暂时无法连接，服务正在启动或重启，请稍后重试。" };
        } else {
          throw error;
        }
      }
      const responseCode = payload && typeof payload === "object" && "error" in payload
        ? String((payload as { error: unknown }).error)
        : "api_request_error";
      const shouldRefreshSession =
        response.status === 401 ||
        (response.status === 403 && responseCode !== "permission_denied" && hasStoredAuthSession());
      if (
        shouldRefreshSession &&
        path !== "/api/auth/refresh" &&
        headers["X-Session-Retry"] !== "1" &&
        !(body instanceof FormData) &&
        !(body instanceof Blob)
      ) {
        if (await refreshSessionOnce()) {
          return apiRequest<T>(path, {
            ...options,
            readCache: false,
            headers: { ...headers, "X-Session-Retry": "1" },
          });
        }
      }
      if (!response.ok) {
        const code = responseCode;
        const message = payload && typeof payload === "object" && "message" in payload ? String((payload as { message: unknown }).message) : code;
        if (isRetryableApiCode(code) && attempt < attempts) {
          await delay(400 * attempt);
          continue;
        }
        if (
          !path.startsWith("/api/auth/") &&
          (response.status === 401 || (response.status === 403 && code === "permission_denied"))
        ) {
          window.dispatchEvent(
            new CustomEvent(sessionRevalidationEvent, {
              detail: { path, status: response.status, code },
            }),
          );
        }
        throw new ApiRequestError(message, response.status, code, payload);
      }
      return payload as T;
    } catch (error) {
      lastError = error;
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new ApiRequestError("请求超时，请确认 Data Agent API 服务可用后重试。", 0, "request_timeout");
      }
      if (error instanceof TypeError && attempt < attempts) {
        await delay(400 * attempt);
        continue;
      }
      if (error instanceof TypeError) {
        throw new ApiRequestError(
          "无法连接 Data Agent API，请确认本地 API 服务已启动。",
          0,
          "network_error",
        );
      }
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
    }
  }
  throw lastError instanceof Error ? lastError : new ApiRequestError("Data Agent API 请求失败，请确认 API 服务已启动后重试。", 0, "api_unavailable");
}

function isRetryableApiCode(code: string) {
  return code === "api_starting" || code === "api_unavailable";
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function refreshSessionOnce(): Promise<boolean> {
  if (sessionRefreshRequest) return sessionRefreshRequest;
  let request: Promise<boolean>;
  request = fetch(`${apiBase}/api/auth/refresh`, {
    method: "POST",
    credentials: "include",
    headers: { Accept: "application/json" },
  })
    .then((response) => response.ok)
    .catch(() => false)
    .finally(() => {
      if (sessionRefreshRequest === request) sessionRefreshRequest = null;
    });
  sessionRefreshRequest = request;
  return request;
}

function apiReadCacheKey(path: string, options: ApiRequestOptions) {
  const requestHeaders = {
    ...(path.startsWith("/api/auth/") ? {} : apiContextHeaders(options.context)),
    ...(options.headers || {}),
  };
  const headerKey = Object.entries(requestHeaders)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key.toLowerCase()}:${value}`)
    .join("|");
  const contextKey = `${options.context?.tenantId || ""}:${options.context?.userId || ""}`;
  return `${apiBase}${path}|${contextKey}|${headerKey}`;
}

function cloneApiPayload<T>(payload: T): T {
  if (typeof structuredClone === "function") return structuredClone(payload);
  return JSON.parse(JSON.stringify(payload)) as T;
}

export function apiErrorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiRequestError) {
    const message = error.message.trim();
    // A proxy or an older API build can return only the machine code. Never
    // expose that raw value in the UI; keep the actionable Chinese guidance
    // while preserving a useful server-side message when one is available.
    if (message && message !== error.code && !/^[a-z][a-z0-9_]*$/.test(message)) return message;
    const knownMessages: Record<string, string> = {
      api_request_error: "Data Agent API 请求失败，请确认 API 服务已启动后重试。",
      api_starting: "Data Agent API 正在启动，请稍后重试。",
      api_unavailable: "无法连接 Data Agent API，服务正在启动或重启，请稍后重试。",
      network_error: "无法连接 Data Agent API，请确认本地 API 服务已启动。",
      request_timeout: "Data Agent API 请求超时，请稍后重试。",
      invalid_json_response: "Data Agent API 返回了无效响应，请稍后重试。",
      analysis_single_data_table_required: "一次分析只能使用一张数据表，请重新选择后重试。",
      customer_segment_detail_table_required: "该数据源不是客户号唯一主键的明细表，不能用于分客群分析。",
      page_data_source_unavailable: "页面数据源已不可用。请检查当前机构的数据目录和页面数据绑定。",
      global_super_admin_required_for_page_data: "仅超级管理员可以新增或修改页面数据。",
    };
    return knownMessages[error.code] || fallback;
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

async function parseJsonPayload(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new ApiRequestError("invalid_json_response", response.status, "invalid_json_response", text.slice(0, 500));
  }
}
