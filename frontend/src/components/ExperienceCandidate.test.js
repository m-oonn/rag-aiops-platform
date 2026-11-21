import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import ExperienceCandidate from "./ExperienceCandidate.vue";
import { session } from "../lib/session";
const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../lib/api", () => ({ request: mocks.request }));
vi.mock("./../lib/ui", async importOriginal => ({ ...await importOriginal(), confirmAction: vi.fn(async () => true) }));
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
  sessionStorage.clear();
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
it('restores the experience review note and selected library after remount', async () => {
  await mountView();
  await wrapper.get('textarea').setValue('保留经验审核意见');
  await wrapper.get('select').setValue('901');
  wrapper.unmount();
  await mountView();
  expect(wrapper.get('textarea').element.value).toBe('保留经验审核意见');
  expect(wrapper.get('select').element.value).toBe('901');
});
it('retains visible notes during retry when browser storage is unavailable', async () => {
  const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {throw Error('quota');});
  mocks.request.mockImplementation(async path => path === '/knowledge-bases' ? [] : {experience:pending});
  try {
    await mountView();
    await wrapper.get('textarea').setValue('存储不可用时保留输入');
    await button('重新读取知识库').trigger('click');
    await flushPromises();
    expect(wrapper.get('textarea').element.value).toBe('存储不可用时保留输入');
  } finally { write.mockRestore(); }
});
it('isolates drafts across reviewers and discards a submitted draft', async () => {
  await mountView();
  await wrapper.get('textarea').setValue('审核者七的意见');
  session.user = {id:8, role:'admin'};
  await flushPromises();
  expect(wrapper.get('textarea').element.value).toBe('');
  session.user = {id:7, role:'admin'};
  await flushPromises();
  expect(wrapper.get('textarea').element.value).toBe('审核者七的意见');
  await wrapper.get('select').setValue('901');
  await button('审核并发布').trigger('click');
  await flushPromises();
  wrapper.unmount();
  await mountView();
  expect(wrapper.get('textarea').element.value).toBe('');
});
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

it("keeps a pending review locked when the empty library retry is clicked", async () => {
  let finish;
  mocks.request.mockImplementation(async (path, options = {}) => {
    if (path === "/knowledge-bases") return [];
    if (options.method === "POST") return new Promise(resolve => { finish = resolve; });
    return { experience: pending };
  });
  await mountView();
  await wrapper.get("textarea").setValue("拒绝缺少依据的候选");
  await button("拒绝候选").trigger("click");
  const reads = mocks.request.mock.calls.filter(([, options]) => !options?.method).length;
  expect(button("重新读取知识库").element.disabled).toBe(true);
  await button("重新读取知识库").trigger("click");
  await button("拒绝候选").trigger("click");
  expect(mocks.request.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
  expect(mocks.request.mock.calls.filter(([, options]) => !options?.method)).toHaveLength(reads);
  finish({ experience: { ...pending, status: "rejected" } });
  await flushPromises();
  expect(wrapper.text()).toContain("已拒绝");
});

it("ignores an old identity mutation while a new identity review is pending", async () => {
  const finishes = [];
  mocks.request.mockImplementation(async (path, options = {}) => {
    if (path === "/knowledge-bases") return [{ id: 901, owner_id: session.user.id, name: "经验库", chunking_config: { retrieval_mode: "bm25" } }];
    if (options.method === "POST") return new Promise(resolve => { finishes.push(resolve); });
    return { experience: pending };
  });
  await mountView();
  await wrapper.get("textarea").setValue("旧账号意见");
  await button("拒绝候选").trigger("click");
  session.user = { id: 8, role: "admin" };
  await flushPromises();
  await wrapper.get("textarea").setValue("新账号意见");
  await button("拒绝候选").trigger("click");
  finishes[0]({ experience: { ...pending, status: "rejected" } });
  await flushPromises();
  expect(button("正在拒绝…").element.disabled).toBe(true);
  expect(wrapper.get("textarea").element.value).toBe("新账号意见");
  finishes[1]({ experience: { ...pending, status: "rejected" } });
  await flushPromises();
  expect(wrapper.text()).toContain("已拒绝");
});

it('lets the reviewer republish a missing document and keeps its history visible', async () => {
  const history = [{action:'publish', kb_id:900, note:'原审核意见'}];
  mocks.request.mockImplementation(async (path, options = {}) => {
    if (path === '/knowledge-bases') return [{id:901, name:'补发库', owner_id:7, chunking_config:{retrieval_mode:'bm25'}}];
    if (options.method === 'POST') return {experience:{...pending, status:'published', version:2, history}};
    return {experience:{...pending, status:'publication_missing', history}};
  });
  await mountView();
  expect(wrapper.text()).toContain('发布文档已移除');
  expect(wrapper.text()).toContain('原审核意见');
  await wrapper.get('select').setValue('901');
  await wrapper.get('textarea').setValue('补发审核');
  await button('审核并补发').trigger('click');
  await flushPromises();
  expect(wrapper.text()).toContain('已发布 · 版本 2');
});
