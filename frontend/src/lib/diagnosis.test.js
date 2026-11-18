import { describe, expect, it } from "vitest";
import { approvalUrl, candidateRows, snapshotSteps } from "./diagnosis";
import { docStatus, evalStatus } from "./ui";

describe("diagnosis projections", () => {
  it("restores readable steps and completed results from actual snapshot payloads", () => {
    const rows = snapshotSteps([
      { node: "planner", payload: { plan: ["[并行] 检查日志", "检查依赖"] } },
      {
        node: "executor",
        payload: { last_step: "检查日志", result_digest: "连接超时" },
      },
      { node: "replanner", payload: { remaining_plan: ["检查依赖"] } },
      { node: "unknown", payload: { secret: "internal" } },
    ]);
    expect(rows).toEqual([
      { text: "检查日志", done: true, result: "连接超时" },
      { text: "检查依赖", done: false, result: "" },
    ]);
  });

  it("uses saved candidates and accepts only web approval links", () => {
    expect(
      candidateRows({
        candidates: [
          {
            id: "h1",
            explanation: "下游连接失败",
            status: "supported",
            evidence_ids: ["ev-123"],
          },
        ],
      }),
    ).toEqual([
      {
        id: "h1",
        text: "下游连接失败",
        status: "有证据支持",
        evidence: ["ev-123"],
      },
    ]);
    expect(approvalUrl("http://127.0.0.1:9000/approval")).toBe(
      "http://127.0.0.1:9000/approval",
    );
    expect(approvalUrl("javascript:alert(1)")).toBe("");
    expect(approvalUrl("file:///private")).toBe("");
  });

  it("matches task and evaluation states to the server contract", () => {
    expect([0, 1, 2, 3, 4].map(evalStatus)).toEqual([
      "待处理",
      "执行中",
      "已完成",
      "失败",
      "待评测",
    ]);
    expect(docStatus("STARTED")).toBe("处理中");
    expect(docStatus("PROCESSING")).toBe("处理中");
  });
});
