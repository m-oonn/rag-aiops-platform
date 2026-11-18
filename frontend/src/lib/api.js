export function errorText(detail) {
  if (Array.isArray(detail))
    return detail
      .map((item) => `${item.loc?.slice(1).join(".") || "字段"}：${item.msg}`)
      .join("；");
  if (typeof detail === "string") return detail;
  return detail?.message || "请求失败，请稍后重试";
}

export async function request(
  path,
  { method = "GET", body, query, signal, blob = false } = {},
) {
  const headers = {};
  const token = localStorage.getItem("token");
  if (token) headers.Authorization = `Bearer ${token}`;
  if (
    body !== undefined &&
    !(body instanceof FormData) &&
    !(body instanceof URLSearchParams)
  ) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  const params = new URLSearchParams();
  Object.entries(query || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "")
      params.set(key, value);
  });
  const response = await fetch(
    `/api/v1${path}${params.size ? `?${params}` : ""}`,
    { method, headers, body, signal },
  );
  if (!response.ok) {
    let data;
    try {
      data = await response.json();
    } catch {
      data = { detail: `请求失败（${response.status}）` };
    }
    if (response.status === 401 && !path.includes("login")) {
      localStorage.removeItem("token");
      window.dispatchEvent(new Event("session-expired"));
    }
    throw Object.assign(new Error(errorText(data.detail || data.message)), {
      status: response.status,
      detail: data.detail,
    });
  }
  if (blob) return response.blob();
  if (response.headers.get("content-type")?.includes("text/event-stream"))
    return response;
  if (response.status === 204) return null;
  return response.json();
}

export async function stream(path, body, { signal, onEvent } = {}) {
  const response = await request(path, { method: "POST", body, signal });
  if (!response.body) throw new Error("未收到服务器数据流");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  function frame(text) {
    const data = text
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data || data === "[DONE]") return;
    let event;
    try {
      event = JSON.parse(data);
    } catch {
      throw new Error("服务器返回了无法读取的数据");
    }
    onEvent?.(event);
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let match;
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        frame(buffer.slice(0, match.index));
        buffer = buffer.slice(match.index + match[0].length);
      }
      if (done) {
        if (buffer.trim()) frame(buffer);
        break;
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
