import { afterEach, describe, expect, it, vi } from "vitest";
import { request, stream } from "./api";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("API requests", () => {
  it("sends the session token and JSON body through the v1 API", async () => {
    localStorage.setItem("token", "session-token");
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => "application/json" },
        json: async () => ({ id: 7 }),
      });
    await expect(
      request("/knowledge-bases/", {
        method: "POST",
        body: { name: "运维知识" },
      }),
    ).resolves.toEqual({ id: 7 });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/knowledge-bases/");
    expect(fetchMock.mock.calls[0][1].headers).toEqual({
      Authorization: "Bearer session-token",
      "Content-Type": "application/json",
    });
    expect(fetchMock.mock.calls[0][1].body).toBe('{"name":"运维知识"}');
  });

  it("shows validation errors and clears a session on 401", async () => {
    localStorage.setItem("token", "expired");
    const expired = vi.fn();
    window.addEventListener("session-expired", expired);
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 422,
      headers: { get: () => "application/json" },
      json: async () => ({
        detail: [{ loc: ["body", "name"], msg: "Field required" }],
      }),
    });
    await expect(
      request("/knowledge-bases/", { method: "POST", body: {} }),
    ).rejects.toMatchObject({ message: "name：Field required", status: 422 });
    expect(expired).not.toHaveBeenCalled();
    expect(localStorage.getItem("token")).toBe("expired");
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 401,
      headers: { get: () => "application/json" },
      json: async () => ({ detail: "Unauthorized" }),
    });
    await expect(request("/auth/me")).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledOnce();
    expect(localStorage.getItem("token")).toBeNull();
    window.removeEventListener("session-expired", expired);
  });

  it("parses an SSE event even when UTF-8 characters and frame boundaries split across chunks", async () => {
    const text = 'data: {"type":"complete","message":"诊断完成"}\r\n\r\n';
    const bytes = new TextEncoder().encode(text);
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(bytes.slice(0, 32));
            controller.enqueue(bytes.slice(32, 41));
            controller.enqueue(bytes.slice(41));
            controller.close();
          },
        }),
        { headers: { "Content-Type": "text/event-stream" } },
      ),
    );
    const events = [];
    await stream(
      "/aiops",
      { query: "服务无响应" },
      { onEvent: (event) => events.push(event) },
    );
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/aiops");
    expect(events).toEqual([{ type: "complete", message: "诊断完成" }]);
  });
});
