export const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim() || "http://127.0.0.1:8000";

export type ApiMethod = "GET" | "POST";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

type RequestOptions = {
  method?: ApiMethod;
  token?: string | null;
  body?: unknown;
  headers?: Record<string, string>;
  isFormData?: boolean;
  timeoutMs?: number;
};

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", token, body, headers = {}, isFormData = false, timeoutMs } = options;
  const controller = timeoutMs ? new AbortController() : undefined;
  const timeoutHandle = timeoutMs
    ? window.setTimeout(() => controller?.abort(), timeoutMs)
    : undefined;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: {
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: body === undefined ? undefined : isFormData ? (body as BodyInit) : JSON.stringify(body),
      signal: controller?.signal,
    });
  } catch (error) {
    if (timeoutHandle) {
      window.clearTimeout(timeoutHandle);
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(408, "The request took too long and was stopped. Please try again. If this keeps happening, the backend is still taking too long for this screen.");
    }
    if (error instanceof TypeError) {
      throw new ApiError(
        0,
        `The backend API is not reachable at ${API_BASE_URL}. Make sure the FastAPI server is running on that address, then try again.`,
      );
    }
    throw error;
  }

  if (timeoutHandle) {
    window.clearTimeout(timeoutHandle);
  }

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload?.detail) {
        detail = payload.detail;
      }
    } catch {
      // ignore json parse failures
    }
    throw new ApiError(response.status, detail);
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }
  return (await response.text()) as T;
}
