import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import ExperienceCandidate from "./ExperienceCandidate.vue";
import { session } from "../lib/session";
const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../lib/api", () => ({ request: mocks.request }));
vi.mock("../lib/session", async () => {
  const { reactive } = await import("vue");
  return { session: reactive({ user: { id: 7, role: "admin" } }) };
});
const pending = { id: "xp-one", status: "pending", version: 1, payload: {
  report: "未确认停止原因", scope: { target_ids: ["local"] }, evidence: [{ evidence_id: "ev-one" }] }, history: [] };
let wrapper;
const button = text => wrapper.findAll("button").find(node => node.text() === text);
beforeEach(() => {
  vi.clearAllMocks();
  session.user = { id: 7, role: "admin" };
  mocks.request.mockImplementation(async (path, options = {}) => {
    if (path === "/knowledge-bases") return [{ id: 901, name: "经验库", owner_id: 7, chunking_config: { retrieval_mode: "bm25" } }];
    return { experience: options.method === "POST" ? { ...pending, status: "published", document_id: 23 } : pending };
  });
});
afterEach(() => wrapper?.unmount());
async function mountView() {
  wrapper = mount(ExperienceCandidate, { props: { threadId: "saved-run", status: "completed" } });
  await flushPromises();
}
it("requires a review note and owned local library before publishing", async () => {
  await mountView();
  expect(wrapper.text()).toContain("待审核");
  expect(wrapper.text()).toContain("不是当前现场事实");
  expect(button("审核并发布").element.disabled).toBe(true);
  await wrapper.get("textarea").setValue("只供连接失败排查参考");
  await wrapper.get("select").setValue("901");
  await button("审核并发布").trigger("click");
  await flushPromises();
  expect(mocks.request).toHaveBeenCalledWith("/aiops/runs/saved-run/experience/review", {
    method: "POST", body: { action: "publish", kb_id: 901, note: "只供连接失败排查参考" } });
  expect(wrapper.text()).toContain("已发布");
  expect(button("撤回经验")).toBeDefined();
});
it("hides review controls from non administrators", async () => {
  session.user.role = "user";
  await mountView();
  expect(button("审核并发布")).toBeUndefined();
  expect(button("拒绝候选")).toBeUndefined();
  expect(mocks.request.mock.calls.some(([path]) => path === "/knowledge-bases")).toBe(false);
});
it("keeps read errors distinct from no candidate", async () => {
  mocks.request.mockRejectedValue(new Error("候选数据库暂不可读"));
  await mountView();
  expect(wrapper.text()).toContain("候选数据库暂不可读");
  expect(button("生成经验候选")).toBeUndefined();
});
it("discards a previous identity response", async () => {
  let resolveOld;
  mocks.request.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  await mountView();
  session.user = { id: 8, role: "user" };
  mocks.request.mockRejectedValue(new Error("无权限"));
  await flushPromises();
  resolveOld({ experience: { ...pending, payload: { ...pending.payload, report: "旧身份内容" } } });
  await flushPromises();
  expect(wrapper.text()).not.toContain("旧身份内容");
  expect(wrapper.text()).toContain("无权限");
});
