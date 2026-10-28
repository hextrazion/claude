// Thin client for the local backend. All provider calls and secrets stay on
// the server; the browser only ever talks to /api on its own origin.

export class ApiError extends Error {
  kind: string;
  detail?: string | null;
  status: number;
  constructor(message: string, kind: string, status: number, detail?: string | null) {
    super(message);
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(method: string, path: string, body?: unknown, isForm = false): Promise<T> {
  const headers: Record<string, string> = { "X-Studio-Client": "web" };
  let payload: BodyInit | undefined;
  if (body !== undefined) {
    if (isForm) payload = body as FormData;
    else {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
  }
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: payload });
  } catch {
    throw new ApiError("Cannot reach the studio backend. Is it still running?", "offline", 0);
  }
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    type ErrBody = { message?: string; kind?: string; detail?: string };
    const err: ErrBody = (data as { error?: ErrBody } | null)?.error ?? {};
    throw new ApiError(err.message || `Request failed (${res.status})`, err.kind || "error", res.status, err.detail);
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return { error: { message: text.slice(0, 300) } };
  }
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string, body?: unknown) => request<T>("DELETE", path, body),
  upload: <T>(path: string, file: File, field = "file") => {
    const fd = new FormData();
    fd.append(field, file);
    return request<T>("POST", path, fd, true);
  },
};

export const fileUrl = (projectId: number, rel?: string | null) =>
  rel ? `/api/files/${projectId}/${rel.split("/").map(encodeURIComponent).join("/")}` : undefined;
