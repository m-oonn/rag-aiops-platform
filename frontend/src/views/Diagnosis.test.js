import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { reactive } from "vue";
import Diagnosis from "./Diagnosis.vue";
import { session } from "../lib/session";
import { rememberRun } from "../lib/history";
const mocks = vi.hoisted(() => ({ request: vi.fn(), stream: vi.fn(), replace: vi.fn(() => Promise.resolve()), route: { query: { run: "saved-run" } } }));
vi.mock("../lib/api", () => ({ request: mocks.request, stream: mocks.stream }));
vi.mock("vue-router", () => ({ useRoute: () => mocks.route, useRouter: () => ({ replace: mocks.replace }) }));
vi.mock("../lib/session", async () => {
  const { reactive } = await import("vue");
  return { session: reactive({ user: { id: 7, role: "user" } }) };
});
const ev = { evidence_id: "ev-0123456789abcdef", kind: "processes", summary: '{"service":"downstream","matched_count":0}', collected_at: "2026-11-14T01:00:00Z" };
const run = { thread_id: "saved-run", status: "completed", diagnosis: { kind: "localized_fault", observed_findings: [{ evidence_id: ev.evidence_id, scope: { service: "downstream" } }] } };
let wrapper;
const button = (text) => wrapper.findAll("button").find(node => node.text() === text);
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  mocks.route = reactive({ query: { run: "saved-run" } });
  mocks.replace.mockImplementation(async location => {
    mocks.route.query = typeof location === "string"
      ? Object.fromEntries(new URL(location, "http://localhost").searchParams)
      : location.query || {};
  });
  session.user = { id: 7, role: "user" };
  mocks.request.mockImplementation(async path => {
    if (path === "/health/dependencies") return { services: {} };
    if (path.endsWith("/steps")) return { steps: [] };
    if (path.endsWith("/tool-calls")) return { tool_calls: [] };
    if (path.endsWith("/evidence")) return { evidence: [ev] };
    if (path.includes(`/evidence/${ev.evidence_id}`)) return { ...ev, raw: { payload: { secret: "private-payload" } }, raw_ref: "internal-file-path" };
    return run;
  });
});
afterEach(() => { wrapper?.unmount(); vi.useRealTimers(); });
const mountView = async () => {
  wrapper = mount(Diagnosis, { global: { stubs: { Modal: { props: ["modelValue"], template: '<div v-if="modelValue" role="dialog"><slot /></div>' } } } });
  await flushPromises();
};
it("shows each persisted tool call, refusal, parameters, result and truncation", async () => {
  const original = mocks.request.getMockImplementation();
  mocks.request.mockImplementation(path => path.endsWith("/tool-calls") ? Promise.resolve({ tool_calls: [{
    call_id: "call-a", tool: "probe_logs", step: "核对失败日志", status: "blocked", reason: "outside_scope",
    arguments: { proposed: { service: "mall" }, executed: {} }, result: "拒绝采集", elapsed_ms: 12,
    result_truncated: true,
  }] }) : original(path));
  await mountView();
  const ledger = wrapper.get('[aria-label="逐次工具调用"]');
  expect(ledger.text()).toContain("核对失败日志");
  expect(ledger.text()).toContain("outside_scope");
  expect(ledger.text()).toContain("mall");
  expect(ledger.text()).toContain("拒绝采集");
  expect(ledger.text()).toContain("结果已截断");
  await button("新建诊断").trigger("click");
  await flushPromises();
  expect(wrapper.find('[aria-label="逐次工具调用"]').exists()).toBe(false);
});
it("keeps a tool audit read failure distinct from zero calls", async () => {
  const original = mocks.request.getMockImplementation();
  mocks.request.mockImplementation(path => path.endsWith("/tool-calls")
    ? Promise.reject(new Error("审计库暂不可读")) : original(path));
  await mountView();
  const ledger = wrapper.get('[aria-label="逐次工具调用"]');
  expect(ledger.text()).toContain("审计库暂不可读");
  expect(ledger.text()).not.toContain("尚无调用记录");
  expect(wrapper.find(".fact-strip").exists()).toBe(true);
});
it("approves a paused report through its own review endpoint", async () => {
  const original = mocks.request.getMockImplementation();
  mocks.request.mockImplementation(path => path === "/aiops/runs/saved-run"
    ? Promise.resolve({ ...run, status: "pending_review", report: "草稿" }) : original(path));
  mocks.stream.mockImplementation(async (_path, _body, { onEvent }) => {
    onEvent({ type: "complete", thread_id: "saved-run", response: "审核后报告" });
  });
  await mountView();
  await button("通过报告").trigger("click");
  await flushPromises();
  expect(mocks.stream).toHaveBeenCalledWith("/aiops/runs/saved-run/review", { action: "approve" }, expect.any(Object));
});
it("restores knowledge references, verifies original chunks through authorized endpoints and clears them for a new run", async () => {
  const original = mocks.request.getMockImplementation();
  const reference = { source: "排查手册.pdf", page: "2", doc_id: 34, kb_id: 15,
    chunk_id: "original-chunk", content: "连接可达不能证明业务正常。", truncated: true };
  mocks.request.mockImplementation(async path => {
    if (path.endsWith("/chunks")) return [{ chunk_uid: "other", content: "无关片段" },
      { chunk_uid: "original-chunk", content: "完整手册：连接可达不能证明业务正常，继续检查失败请求。" }];
    if (path.endsWith("/preview")) return new Blob(["原文"], { type: "text/plain" });
    return path === "/aiops/runs/saved-run" ? { ...run, knowledge_references: [reference] } : original(path);
  });
  await mountView();
  const sources = wrapper.get('[aria-label="本轮知识参考"]');
  expect(sources.text()).toContain("仅供选择排查方法");
  expect(sources.text()).toContain("排查手册.pdf · 第 2 页");
  expect(sources.text()).toContain(reference.content);
  expect(sources.text()).toContain("片段已截短");
  expect(sources.findAll("details")[0].attributes("open")).toBeUndefined();
  expect(mocks.request.mock.calls.some(([path]) => path.endsWith("/preview"))).toBe(false);
  await button("核对原文").trigger("click");
  await flushPromises();
  expect(mocks.request).toHaveBeenCalledWith("/knowledge-bases/documents/34/chunks", { query: { limit: 100 } });
  expect(mocks.request).toHaveBeenCalledWith("/knowledge-bases/documents/34/preview", { blob: true });
  expect(wrapper.get('[role="dialog"]').text()).toContain("完整手册：连接可达不能证明业务正常，继续检查失败请求。");
  expect(wrapper.get('[role="dialog"]').text()).not.toContain("无关片段");
  await button("新建诊断").trigger("click");
  await flushPromises();
  expect(wrapper.find('[aria-label="本轮知识参考"]').exists()).toBe(false);
  expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
});

it("shows a knowledge original permission error without substituting another document", async () => {
  const original = mocks.request.getMockImplementation();
  mocks.request.mockImplementation(async path => {
    if (path.includes("/knowledge-bases/documents/")) throw new Error("无权读取原文");
    return path === "/aiops/runs/saved-run" ? { ...run, knowledge_references: [
      { source: "排查手册.pdf", page: "1", doc_id: 34, chunk_id: "c1", content: "历史检索片段" },
    ] } : original(path);
  });
  await mountView();
  await button("核对原文").trigger("click");
  await flushPromises();
  expect(wrapper.get('[role="dialog"]').text()).toContain("无权读取原文");
  expect(wrapper.get('[role="dialog"]').text()).not.toContain("已核对");
});
it("never renders privileged evidence for an ordinary user even if a response contains it", async () => {
  await mountView();
  await wrapper.get(".fact-strip button").trigger("click");
  await button("来源与原文").trigger("click");
  await flushPromises();
  expect(button("读取现场原文")).toBeUndefined();
  expect(wrapper.text()).not.toContain("private-payload");
  expect(wrapper.text()).not.toContain("internal-file-path");
});
it("keeps the evidence number stable when the source dialog loads one item", async () => {
  const request = mocks.request.getMockImplementation();
  mocks.request.mockImplementation(async path => path.endsWith("/evidence")
    ? { evidence: [{ ...ev, evidence_id: "ev-earlier-record", collected_at: "2026-11-14T00:59:00Z" }, ev] }
    : request(path));
  await mountView();
  await wrapper.get(".fact-strip button").trigger("click");
  expect(wrapper.get(".evidence-heading").text()).toContain("E02");
  await button("来源与原文").trigger("click");
  await flushPromises();
  expect(wrapper.get('[role="dialog"]').text()).toContain("E02");
});
it("clears already displayed raw evidence when permission is revoked", async () => {
  session.user.role = "admin";
  await mountView();
  await wrapper.get(".fact-strip button").trigger("click");
  await button("来源与原文").trigger("click");
  await flushPromises();
  await button("读取现场原文").trigger("click");
  expect(wrapper.text()).toContain("private-payload");
  session.user.role = "user";
  await flushPromises();
  expect(wrapper.text()).not.toContain("private-payload");
  expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
});
it("ignores an old refresh response after the user starts a new diagnosis", async () => {
  await mountView();
  let finish;
  mocks.request.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  await button("重新载入").trigger("click");
  await button("新建诊断").trigger("click");
  finish(run);
  await flushPromises();
  expect(wrapper.find(".fact-strip").exists()).toBe(false);
  expect(wrapper.get("textarea").element.value).toBe("");
  expect(wrapper.get("textarea").attributes("disabled")).toBeUndefined();
  expect(wrapper.text()).not.toContain("故障层已定位");
});
it("starts a new stream, shows actual evidence and can stop reading while the form is collapsed", async () => {
  await mountView();
  await button("新建诊断").trigger("click");
  let emit;
  mocks.stream.mockImplementation((_path, _body, { signal, onEvent }) => {
    emit = onEvent;
    onEvent({ type: "plan", thread_id: "fresh-run", plan: ["检查进程"] });
    onEvent({ type: "evidence", ...ev });
    return new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))));
  });
  await wrapper.get("textarea").setValue("  业务接口超时  ");
  await wrapper.get("form").trigger("submit");
  expect(mocks.stream.mock.calls[0][1]).toMatchObject({ query: "业务接口超时", terminal_enabled: false });
  expect(wrapper.find("textarea").exists()).toBe(false);
  expect(wrapper.get('[role="tab"][aria-selected="true"]').text()).toContain("排查过程");
  expect(wrapper.findAll(".check-list li")).toHaveLength(1);
  await button("停止读取").trigger("click");
  await flushPromises();
  expect(wrapper.text()).toContain("诊断连接已中断");
  await button("新建诊断").trigger("click");
  emit({ type: "evidence", ...ev });
  await flushPromises();
  expect(wrapper.findAll(".check-list li")).toHaveLength(0);
});

it("restores the last viewed diagnosis and evidence when returning through the sidebar", async () => {
  await mountView();
  wrapper.unmount();
  mocks.route.query = {};
  mocks.request.mockClear();
  await mountView();
  expect(wrapper.text()).toContain("故障层已定位");
  expect(wrapper.find(".fact-strip").exists()).toBe(true);
  expect(mocks.route.query).toEqual({ run: "saved-run" });
  expect(mocks.request).toHaveBeenCalledWith("/aiops/runs/saved-run/evidence");
  expect(mocks.stream).not.toHaveBeenCalled();
});

it("updates a restored running diagnosis from persisted state without submitting again", async () => {
  vi.useFakeTimers();
  const original = mocks.request.getMockImplementation();
  let current = { ...run, status: "running", report: "" };
  mocks.request.mockImplementation(path => path === "/aiops/runs/saved-run" ? Promise.resolve(current) : original(path));
  await mountView();
  current = { ...run, report: "持久化完成报告" };
  await vi.advanceTimersByTimeAsync(1500);
  await flushPromises();
  expect(wrapper.text()).toContain("已完成");
  expect(wrapper.text()).toContain("持久化完成报告");
  expect(mocks.stream).not.toHaveBeenCalled();
  const reads = mocks.request.mock.calls.length;
  await vi.advanceTimersByTimeAsync(3000);
  expect(mocks.request.mock.calls.length).toBe(reads);
});

it("keeps an explicitly new diagnosis blank after refresh instead of reopening history", async () => {
  await mountView();
  await button("新建诊断").trigger("click");
  await flushPromises();
  expect(mocks.route.query).toEqual({ new: "1" });
  wrapper.unmount();
  mocks.request.mockClear();
  await mountView();
  expect(wrapper.get("textarea").element.value).toBe("");
  expect(wrapper.find(".fact-strip").exists()).toBe(false);
  expect(mocks.request.mock.calls.filter(([path]) => path.startsWith("/aiops/runs/"))).toHaveLength(0);
});

it("does not restore another account's last diagnosis", async () => {
  rememberRun(8, { thread_id: "another-user-run", query: "另一位用户的问题" });
  mocks.route.query = {};
  await mountView();
  expect(wrapper.get("textarea").element.value).toBe("");
  expect(mocks.request.mock.calls.filter(([path]) => path.startsWith("/aiops/runs/"))).toHaveLength(0);
});

it("keeps an unavailable saved run visible as an error without retrying it in a loop", async () => {
  rememberRun(7, { thread_id: "saved-run", query: "以前的问题" });
  const request = mocks.request.getMockImplementation();
  mocks.request.mockImplementation(path => path === "/aiops/runs/saved-run"
    ? Promise.reject(Object.assign(new Error("诊断记录不存在"), { status: 404 }))
    : request(path));
  await mountView();
  expect(wrapper.text()).toContain("诊断记录不存在");
  expect(mocks.route.query).toEqual({ run: "saved-run" });
  expect(mocks.request.mock.calls.filter(([path]) => path === "/aiops/runs/saved-run")).toHaveLength(1);
});

it("restores the server query when this browser has no history", async () => {
  const original = mocks.request.getMockImplementation();
  mocks.request.mockImplementation(path => path === "/aiops/runs/saved-run"
    ? Promise.resolve({ ...run, query: "服务器保存的原始故障" }) : original(path));
  await mountView();
  await button("故障描述").trigger("click");
  expect(wrapper.get("textarea").element.value).toBe("服务器保存的原始故障");
});

it("continues polling after a transient run read failure", async () => {
  vi.useFakeTimers();
  const original = mocks.request.getMockImplementation();
  let reads = 0;
  mocks.request.mockImplementation(path => {
    if (path !== "/aiops/runs/saved-run") return original(path);
    if (++reads === 2) return Promise.reject(new Error("暂时断网"));
    return Promise.resolve({ ...run, status: reads < 3 ? "running" : "completed", report: reads < 3 ? "" : "恢复后的报告" });
  });
  await mountView();
  await vi.advanceTimersByTimeAsync(1500);
  await vi.advanceTimersByTimeAsync(1500);
  await flushPromises();
  expect(wrapper.text()).toContain("恢复后的报告");
  expect(wrapper.text()).not.toContain("暂时断网");
});

it("loads approval information when a running run pauses during polling", async () => {
  vi.useFakeTimers();
  const original = mocks.request.getMockImplementation();
  let current = { ...run, status: "running" };
  mocks.request.mockImplementation(path => path === "/aiops/runs/saved-run" ? Promise.resolve(current) : original(path));
  await mountView();
  current = { ...run, status: "pending_terminal", terminal_approval: { command: "read status" }, termcp_ui_url: "https://approval.example/check" };
  await vi.advanceTimersByTimeAsync(1500);
  await flushPromises();
  expect(wrapper.text()).toContain("read status");
  expect(wrapper.get('a[href="https://approval.example/check"]').exists()).toBe(true);
});

it("can retry an initial restore error through the run toolbar", async () => {
  const original = mocks.request.getMockImplementation();
  let reads = 0;
  mocks.request.mockImplementation(path => path === "/aiops/runs/saved-run" && ++reads === 1
    ? Promise.reject(new Error("临时读取失败")) : original(path));
  await mountView();
  expect(button("重新载入")?.element.disabled).toBe(false);
  await button("重新载入").trigger("click");
  await flushPromises();
  expect(wrapper.text()).toContain("故障层已定位");
});

it("retains an unsent draft and terminal choice when leaving and returning", async () => {
  mocks.route.query = { new: "1" };
  await mountView();
  await wrapper.get("textarea").setValue("还未提交的故障现象");
  await wrapper.get('input[type="checkbox"]').setValue(true);
  wrapper.unmount();
  await mountView();
  expect(wrapper.get("textarea").element.value).toBe("还未提交的故障现象");
  expect(wrapper.get('input[type="checkbox"]').element.checked).toBe(true);
});

it("does not let older audit reads erase newer evidence from the same run", async () => {
  await mountView();
  const original = mocks.request.getMockImplementation();
  let finishOld;
  mocks.request.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve; }));
  const oldRead = wrapper.vm.loadEvidence();
  mocks.request.mockImplementation(path => path.endsWith("/evidence") ? Promise.resolve({ evidence: [ev, { ...ev, evidence_id: "ev-new-record" }] }) : original(path));
  await wrapper.vm.loadEvidence();
  finishOld({ evidence: [ev] });
  await oldRead;
  await flushPromises();
  expect(wrapper.findComponent({ name: "DiagnosisWorkspace" }).props("evidence")).toHaveLength(2);
});

it("treats an empty persisted report as authoritative after refresh", async () => {
  const original = mocks.request.getMockImplementation();
  let current = { ...run, report: "旧草稿" };
  mocks.request.mockImplementation(path => path === "/aiops/runs/saved-run" ? Promise.resolve(current) : original(path));
  await mountView();
  current = { thread_id: "saved-run", status: "failed", report: "", diagnosis: null };
  await wrapper.vm.refreshRunDetails();
  await flushPromises();
  expect(wrapper.findComponent({ name: "DiagnosisWorkspace" }).props("report")).toBe("");
  expect(wrapper.findComponent({ name: "DiagnosisWorkspace" }).props("diagnosis")).toBeNull();
});

it("does not mark the saved history running again after a final usage event", async () => {
  mocks.route.query = { new: "1" };
  mocks.stream.mockImplementation(async (_path, _body, { onEvent }) => {
    onEvent({ type: "complete", thread_id: "new-run", response: "结果" });
    onEvent({ type: "usage", thread_id: "new-run", llm_calls: 1 });
  });
  await mountView();
  await wrapper.get("textarea").setValue("问题");
  await wrapper.get("form").trigger("submit");
  await flushPromises();
  const rows = JSON.parse(localStorage.getItem("aiops:runs:v2:7"));
  expect(rows.find(row => row.thread_id === "new-run").status).toBe("completed");
});

it("does not transfer an unsent diagnosis to another identity", async () => {
  mocks.route.query = { new: "1" };
  await mountView();
  await wrapper.get("textarea").setValue("账号7的私有输入");
  session.user = { id: 8, role: "user" };
  await flushPromises();
  expect(wrapper.get("textarea").element.value).toBe("");
  expect(sessionStorage.getItem("aiops:draft:8") || "").not.toContain("账号7的私有输入");
});
