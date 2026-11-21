import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { nextTick } from "vue";
import DiagnosisWorkspace from "./DiagnosisWorkspace.vue";
import { session } from "../lib/session";
const evidence = Array.from({ length: 10 }, (_, index) => ({ evidence_id: `ev-${String(index).padStart(16, "0")}`, kind: "processes", target_id: "host", summary: JSON.stringify({ service: index % 2 ? "downstream" : "app", matched_count: index % 2 ? 0 : 1 }), collected_at: `2026-11-14T01:07:${String(index).padStart(2, "0")}Z` }));
const props = { runId: "saved-run", status: "completed", evidence, plans: Array.from({ length: 6 }, (_, index) => ({ text: `计划${index + 1}`, done: false })), diagnosis: { kind: "localized_fault", observed_findings: [{ evidence_id: evidence[1].evidence_id, scope: { service: "downstream" } }] }, investigation: { candidates: [{ id: "h1", explanation: "下游停止", status: "active", relation: "neutral", evidence_ids: [evidence[1].evidence_id] }] } };
const button = (wrapper, text) => wrapper.findAll("button").find(node => node.text() === text);
let wrapper;
beforeEach(() => { sessionStorage.clear(); session.user = { id: 7, role: "user" }; });
afterEach(() => { wrapper?.unmount(); vi.useRealTimers(); });
describe("diagnosis workspace interactions", () => {
  it("restores navigation, evidence and replay cursor after remount without following later status", async () => {
    wrapper = mount(DiagnosisWorkspace, { props });
    await wrapper.get("#diagnosis-tab-process").trigger("click");
    await wrapper.findAll(".check-list button")[4].trigger("click");
    wrapper.unmount();
    wrapper = mount(DiagnosisWorkspace, { props });
    expect(wrapper.get('[aria-current="step"]').text()).toContain("05");
    await wrapper.get("#diagnosis-tab-evidence").trigger("click");
    await wrapper.findAll(".evidence-index button")[2].trigger("click");
    const heading = wrapper.get(".evidence-heading").text();
    wrapper.unmount();
    wrapper = mount(DiagnosisWorkspace, { props });
    expect(wrapper.get(".evidence-heading").text()).toBe(heading);
    await wrapper.setProps({ status: "running" });
    expect(wrapper.get('[role="tab"][aria-selected="true"]').text()).toContain("现场证据");
    await wrapper.setProps({ runId: "other-run" });
    expect(wrapper.get('[role="tab"][aria-selected="true"]').text()).toContain("排查过程");
  });

  it("restores the selected candidate only for its user and run", async () => {
    const options = { ...props, investigation: { candidates: [...props.investigation.candidates,
      { id: "h2", explanation: "第二个候选", status: "active" }] } };
    wrapper = mount(DiagnosisWorkspace, { props: options });
    await wrapper.get("#diagnosis-tab-causes").trigger("click");
    await wrapper.findAll(".candidate-index button")[1].trigger("click");
    wrapper.unmount();
    wrapper = mount(DiagnosisWorkspace, { props: options });
    expect(wrapper.get(".candidate-detail h2").text()).toContain("第二个候选");
    session.user = { id: 8, role: "user" };
    await nextTick();
    expect(wrapper.get('[role="tab"][aria-selected="true"]').text()).toContain("诊断报告");
  });
  it("does not show another business from host inventory while registration is pending", async () => {
    wrapper = mount(DiagnosisWorkspace, { props: { status: 'running', diagnosis: {}, evidence: [
      { evidence_id: 'catalog', kind: 'inventory', summary: JSON.stringify({ configured_services: { ecom_web: {}, mall_portal: {}, mall_mysql: {} } }) },
      { evidence_id: 'actual', kind: 'services', summary: JSON.stringify({ service: 'mall_portal', state: 'running' }) },
    ] } });
    expect(wrapper.text()).not.toContain('商城网站');
    expect(wrapper.text()).toContain('商城买家业务服务');
    await wrapper.setProps({ diagnosis: { asset_registration: { allowed_services: ['mall_portal', 'mall_mysql'] } } });
    expect(wrapper.text()).not.toContain('商城网站');
    expect(wrapper.text()).toContain('商城数据库');
  });
  it("lets a reader verify registered and actual resource directories in the cited evidence", async () => {
    wrapper = mount(DiagnosisWorkspace, { props: { ...props, evidence: [{ evidence_id: 'static-config', kind: 'configuration',
      summary: JSON.stringify({ service: 'ecom_web', values: { static_files: { 'shop.css': { found: false } } },
        static_mounts: [{ destination: '/lab/static', registered_source: 'D:/registered', actual_source: 'D:/empty',
          registered_resources_present: { 'shop.css': true } }] }) }] } });
    expect(wrapper.find('.resource-mapping').exists()).toBe(false);
    await wrapper.get('#diagnosis-tab-evidence').trigger('click');
    const mapping = wrapper.get('[aria-label="资源目录实际映射"]');
    expect(mapping.text()).toContain('登记的来源目录D:/registered');
    expect(mapping.text()).toContain('实际使用的来源目录D:/empty');
    expect(mapping.text()).toContain('登记目录中的 shop.css文件存在');
    expect(wrapper.get('.evidence-heading').text()).toContain('E01');
  });
  it("preserves unresolved questions with the model's unverified scope reasoning", () => {
    wrapper = mount(DiagnosisWorkspace, { props: { ...props, diagnosis: {
      ...props.diagnosis, unresolved_questions: [{ question: "其他代码问题" }],
      alternatives: [{ explanation: "其他代码问题", status: "unresolved", critical: false,
        noncritical_reason: "本次失败发生在连接阶段" }],
    } } });
    expect(wrapper.get(".findings-summary").text()).toContain("其他代码问题");
    expect(wrapper.get(".question-boundary summary").text()).toContain("模型判断");
    expect(wrapper.get(".question-boundary").text()).toContain("仍未独立核验");
    expect(wrapper.get(".question-boundary").text()).toContain("本次失败发生在连接阶段");
    expect(wrapper.get(".question-boundary").attributes("open")).toBeUndefined();
  });
  it("keeps detailed validation limits expandable and preserves unresolved questions", () => {
    wrapper = mount(DiagnosisWorkspace, { props: { ...props, diagnosis: {
      ...props.diagnosis, limitations: ["内部校验原文 upstream_request.phase"],
      unresolved_questions: ["其他业务路径是否受影响尚未确认", { question: 'dependency_probe/ecom_redis: tcp == "failed"' }],
    } } });
    expect(wrapper.get(".evidence-limits").attributes("open")).toBeUndefined();
    expect(wrapper.get(".evidence-limits summary").text()).toContain("1 项");
    expect(wrapper.get(".evidence-limits").text()).toContain("upstream_request.phase");
    expect(wrapper.get(".findings-summary").text()).toContain("其他业务路径是否受影响尚未确认");
    expect(wrapper.get(".findings-summary").text()).toContain("尚未确认：缓存与会话 TCP 连接失败");
  });
  it("keeps the overview short, makes the chain actionable and retains the complete original", async () => {
    const log = (id, service, lines) => ({ evidence_id: id, kind: "text_logs", target_id: "host", summary: JSON.stringify({ service, lines: lines.map(data => JSON.stringify(data)) }) });
    const logs = [log("down", "downstream", [{ event: "service_started", listen_port: 4634 }, { event: "shutdown_requested" }, { event: "service_exited" }]),
      log("app", "localapp", [{ event: "service_started", listen_port: 4633, upstream: { host: "127.0.0.1", port: 4634 } }, { status: 503, request_id: "same", upstream_request: { connection_established: false } }])];
    wrapper = mount(DiagnosisWorkspace, { props: { ...props, evidence: logs, report: "完整原文 controlled_stop pid=123", diagnosis: { kind: "confirmed_cause", root_cause_code: "downstream_stopped_after_request", hypothesis_id: "root", conclusion: "长原文 controlled_stop pid=123", evidence: logs.map(row => ({ evidence_id: row.evidence_id })), recommendations: [{ action: "保存日志后由人启动 downstream。", preconditions: ["确认恢复窗口"], verification_steps: ["重新请求业务接口"] }] }, investigation: { candidates: [{ id: "root", explanation: "原始候选", status: "active" }, { id: "old", explanation: "此前的猜测", status: "dropped" }] } } });
    expect(wrapper.get(".report-lead h2").text()).toBe("下游服务停止，业务请求失败");
    expect(wrapper.get(".report-lead").text()).not.toContain("controlled_stop");
    expect(wrapper.findAll(".failure-flow li")).toHaveLength(2);
    expect(wrapper.findAll("details").find(node => node.text().includes("完整原文")).attributes("open")).toBeUndefined();
    expect(wrapper.get(".action-row summary").text()).toContain("请运维人员恢复下游服务");
    await wrapper.get(".action-row summary").trigger("click");
    expect(wrapper.get(".action-content").text()).toContain("保存日志后由人启动 downstream。");
    expect(wrapper.get(".action-content").text()).toContain("重新请求业务接口");
    await wrapper.get(".failure-flow button").trigger("click");
    expect(wrapper.get(".evidence-heading").text()).toContain("E01");
    await wrapper.get("#diagnosis-tab-causes").trigger("click");
    expect(wrapper.get(".candidate-detail").text()).toContain("已确认原因");
    expect(wrapper.findAll(".relation-node.citation")).toHaveLength(2);
    expect(wrapper.get(".relation-node.citation").text()).toContain("结论依据");
    await wrapper.get(".relation-node.citation").trigger("click");
    expect(wrapper.get(".evidence-heading").text()).toContain("E01");
    await wrapper.get("#diagnosis-tab-causes").trigger("click");
    expect(wrapper.get(".candidate-history summary").text()).toBe("此前排查 · 1");
    expect(wrapper.get(".candidate-history").attributes("open")).toBeUndefined();
    expect(wrapper.find(".candidate-gap").exists()).toBe(false);
  });
  it("links facts to grouped evidence and requests raw details only on demand", async () => {
    wrapper = mount(DiagnosisWorkspace, { props });
    expect(wrapper.text()).toContain("故障层已定位 · 原因待确认");
    expect(wrapper.emitted("evidence")).toBeUndefined();
    await wrapper.get(".fact-strip button").trigger("click");
    expect(wrapper.get('[role="tab"][aria-selected="true"]').text()).toContain("现场证据");
    expect(wrapper.get(".evidence-heading").text()).toContain("E02");
    await button(wrapper, "来源与原文").trigger("click");
    expect(wrapper.emitted("evidence")).toEqual([[evidence[1].evidence_id]]);
    await button(wrapper, "返回诊断报告").trigger("click");
    expect(wrapper.get('#diagnosis-tab-report').attributes("aria-selected")).toBe("true");
  });
  it("replays ten actual records, pauses and stops at the end without looping", async () => {
    vi.useFakeTimers();
    wrapper = mount(DiagnosisWorkspace, { props });
    await wrapper.get("#diagnosis-tab-process").trigger("click");
    expect(wrapper.findAll(".check-list li")).toHaveLength(10);
    expect(wrapper.text()).toContain("排查计划 · 0/6 项完成");
    await button(wrapper, "回放").trigger("click");
    await vi.advanceTimersByTimeAsync(1600);
    expect(wrapper.get('[aria-current="step"]').text()).toContain("02");
    await button(wrapper, "暂停").trigger("click");
    await vi.advanceTimersByTimeAsync(3200);
    expect(wrapper.get('[aria-current="step"]').text()).toContain("02");
    await button(wrapper, "回放").trigger("click");
    await vi.advanceTimersByTimeAsync(1600 * 10);
    expect(wrapper.get('[aria-current="step"]').text()).toContain("10");
    expect(button(wrapper, "重新回放")).toBeTruthy();
    expect(vi.getTimerCount()).toBe(0);
    await button(wrapper, "重新回放").trigger("click");
    await wrapper.get("#diagnosis-tab-report").trigger("click");
    expect(vi.getTimerCount()).toBe(0);
  });
  it("keeps the live cursor independent of tabs and retains a manually selected record when data arrives", async () => {
    wrapper = mount(DiagnosisWorkspace, { props: { ...props, status: "running", evidence: evidence.slice(0, 8) } });
    await wrapper.get("#diagnosis-tab-evidence").trigger("click");
    await wrapper.get("#diagnosis-tab-process").trigger("click");
    expect(button(wrapper, "跟随最新").attributes("aria-pressed")).toBe("true");
    await wrapper.setProps({ evidence: evidence.slice(0, 9) });
    expect(wrapper.get('[aria-current="step"]').text()).toContain("09");
    await wrapper.findAll(".check-list button")[2].trigger("click");
    await wrapper.setProps({ evidence });
    expect(wrapper.get('[aria-current="step"]').text()).toContain("03");
    expect(button(wrapper, "跟随最新").attributes("aria-pressed")).toBe("false");
  });
  it("keeps an unresolved cause unresolved and links its evidence without fabricating support", async () => {
    wrapper = mount(DiagnosisWorkspace, { props });
    await wrapper.get("#diagnosis-tab-causes").trigger("click");
    expect(wrapper.get(".candidate-detail").text()).toContain("待验证");
    expect(wrapper.get(".relation-node").text()).toContain("关系未定");
    expect(wrapper.find(".relation-node.support").exists()).toBe(false);
    await wrapper.get(".relation-node").trigger("click");
    expect(wrapper.get(".evidence-heading").text()).toContain("E02");
  });
  it("clears playback on unmount and hides observations from a prior run on reset", async () => {
    vi.useFakeTimers();
    wrapper = mount(DiagnosisWorkspace, { props });
    await wrapper.get("#diagnosis-tab-process").trigger("click");
    await button(wrapper, "回放").trigger("click");
    await wrapper.setProps({ runId: "", evidence: [], diagnosis: null, investigation: null, plans: [] });
    await nextTick();
    expect(wrapper.findAll(".check-list li")).toHaveLength(0);
    expect(vi.getTimerCount()).toBe(0);
    expect(wrapper.text()).not.toContain("downstream");
  });
});
