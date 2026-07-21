import { apiContextHeaders, type ApiContextParams } from "./apiContext";

type ApiRequestOptions = Omit<RequestInit, "body" | "headers" | "signal"> & {
  body?: unknown;
  context?: ApiContextParams;
  headers?: Record<string, string>;
  timeoutMs?: number;
};

const apiBase = (import.meta.env.VITE_ANALYSIS_API_URL || "").replace(/\/$/, "");

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
  const {
    body,
    context,
    headers = {},
    timeoutMs = 12000,
    ...requestInit
  } = options;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
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

    const response = await fetch(`${apiBase}${path}`, {
      ...requestInit,
      credentials: "include",
      headers: requestHeaders,
      body: requestBody,
      signal: controller.signal,
    });
    if (
      response.status === 401 &&
      path !== "/api/auth/refresh" &&
      headers["X-Session-Retry"] !== "1" &&
      !(body instanceof FormData) &&
      !(body instanceof Blob)
    ) {
      const refreshResponse = await fetch(`${apiBase}/api/auth/refresh`, {
        method: "POST",
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      if (refreshResponse.ok) {
        return apiRequest<T>(path, {
          ...options,
          headers: { ...headers, "X-Session-Retry": "1" },
        });
      }
    }
    const payload = await parseJsonPayload(response);
    if (!response.ok) {
      const code = payload && typeof payload === "object" && "error" in payload ? String(payload.error) : "api_request_error";
      const message = payload && typeof payload === "object" && "message" in payload ? String(payload.message) : code;
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
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiRequestError("请求超时，请确认 Data Agent API 服务可用后重试。", 0, "request_timeout");
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

export function apiErrorMessage(error: unknown, fallback: string) {
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
