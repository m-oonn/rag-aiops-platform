import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import Dashboard from "./Dashboard.vue";
import { session } from "../lib/session";
import { rememberRun } from "../lib/history";
const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../lib/api", () => ({ request: mocks.request }));
vi.mock("../lib/session", async () => {
  const { reactive } = await import("vue");
  return { session: reactive({ user: { id: 7 } }) };
});
let wrapper;
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  session.user = {id:7};
  mocks.request.mockImplementation(async path => path === '/aiops/runs' ? {runs:[]} : path.startsWith('/aiops/runs/')
    ? {status:'completed', updated_at:'2026-11-18T12:00:00Z'} : []);
});
afterEach(() => wrapper?.unmount());
it('refreshes recent diagnoses from the server and keeps failures unverified', async () => {
  rememberRun(7, {thread_id:'first', query:'旧描述', status:'running'});
  wrapper = mount(Dashboard);
  await flushPromises();
  expect(wrapper.find('.record-row').text()).toContain('已完成');
  mocks.request.mockImplementation(async path => {
    if (path.startsWith('/aiops/runs/')) throw new Error('暂不可读');
    return [];
  });
  await wrapper.findAll('button').find(b => b.text().includes('刷新')).trigger('click');
  await flushPromises();
  expect(wrapper.find('.record-row').text()).toContain('状态未核实');
});
it('recovers recent diagnoses from the server when browser storage is empty', async () => {
  mocks.request.mockImplementation(async path => path === '/aiops/runs'
    ? {runs:[{thread_id:'server-run', query:'服务器恢复记录', status:'completed', updated_at:'2026-11-18T12:00:00Z'}]}
    : path === '/aiops/runs/server-run'
      ? {thread_id:'server-run', query:'服务器恢复记录', status:'completed', updated_at:'2026-11-18T12:00:00Z'} : []);
  wrapper = mount(Dashboard);
  await flushPromises();
  expect(wrapper.find('.record-row').text()).toContain('服务器恢复记录');
});
it('isolates recent diagnoses on an identity change and ignores late reads', async () => {
  let finish;
  rememberRun(7, {thread_id:'old', query:'旧账号诊断', status:'running'});
  mocks.request.mockImplementation(path => path === '/aiops/runs/old'
    ? new Promise(resolve => {finish=resolve;}) : Promise.resolve([]));
  wrapper = mount(Dashboard);
  await flushPromises();
  rememberRun(8, {thread_id:'new', query:'新账号诊断', status:'running'});
  session.user = {id:8};
  await flushPromises();
  finish({status:'completed', query:'旧账号晚到结果'});
  await flushPromises();
  expect(wrapper.text()).toContain('新账号诊断');
  expect(wrapper.text()).not.toContain('旧账号');
});
