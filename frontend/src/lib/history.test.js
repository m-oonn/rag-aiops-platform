import { afterEach, describe, expect, it } from "vitest";
import { getHistory, markHistoryRunUnavailable, rememberRun, validRunId } from "./history";

afterEach(() => localStorage.clear());

describe("saved diagnosis history", () => {
  it("rejects malformed run IDs and retains only the latest record for a run", () => {
    expect(validRunId("123e4567-e89b-42d3-a456-426614174000")).toBe(true);
    expect(validRunId("../another-user/run")).toBe(false);
    rememberRun(4, {
      thread_id: "run-42",
      query: "服务返回 503",
      status: "running",
    });
    rememberRun(4, { thread_id: "run-42", status: "completed" });
    expect(getHistory(4)).toHaveLength(1);
    expect(getHistory(4)[0]).toMatchObject({
      thread_id: "run-42",
      query: "服务返回 503",
      status: "completed",
    });
  });
  it("clears cached diagnosis when detail refresh is unavailable", () => {
    const row = {thread_id: "r", diagnosis: {kind: "localized_fault"}, details_status: "available"};
    expect(markHistoryRunUnavailable(row, new Error("详情暂不可读取"))).toMatchObject({
      diagnosis: null, details_status: "unavailable", readError: "详情暂不可读取", knowledge_references: [],
    });
  });

  it("keeps valid records when old storage contains null or duplicate rows", () => {
    localStorage.setItem("aiops:runs:v2:4", JSON.stringify([null, { thread_id: "r" }, { thread_id: "r" }, 2, { thread_id: "other" }]));
    expect(getHistory(4).map(row => row.thread_id)).toEqual(["r", "other"]);
  });
  it("uses the server run ID contract including dotted session prefixes", () => {
    expect(validRunId("service.v1-abcd")).toBe(true);
    expect(validRunId("a".repeat(65))).toBe(false);
  });
  it("preserves the actual server update time when reading a run", () => {
    rememberRun(4, { thread_id: "r", updated_at: "2026-11-01T00:00:00Z" });
    expect(getHistory(4)[0].updated_at).toBe("2026-11-01T00:00:00Z");
  });
});
