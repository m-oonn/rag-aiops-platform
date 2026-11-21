import { afterEach, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import DiagnosisHistory from "./DiagnosisHistory.vue";
import { rememberRun } from "../lib/history";
vi.mock("../lib/session", () => ({session:{user:{id:7}}}));
vi.mock("../lib/api", () => ({request:vi.fn(async path => path === '/aiops/runs' ? {runs:[]} : ({
  status:'completed', updated_at: path.endsWith('/older') ? '2026-11-18T14:00:00Z' : '2026-11-18T13:00:00Z',
}))}));
let wrapper;
afterEach(() => wrapper?.unmount());
it('reorders the visible history after authoritative update times change', async () => {
  localStorage.clear();
  rememberRun(7,{thread_id:'older',query:'原本旧诊断',updated_at:'2026-11-18T10:00:00Z'});
  rememberRun(7,{thread_id:'newer',query:'原本新诊断',updated_at:'2026-11-18T11:00:00Z'});
  wrapper = mount(DiagnosisHistory);
  await flushPromises();
  expect(wrapper.findAll('.cell-title')[0].text()).toContain('原本旧诊断');
});
it('recovers a server run after this browser history has been cleared', async () => {
  localStorage.clear();
  const { request } = await import('../lib/api');
  request.mockImplementation(async path => path === '/aiops/runs'
    ? {runs:[{thread_id:'server-run', query:'恢复的诊断', status:'completed', updated_at:'2026-11-18T15:00:00Z'}]}
    : {thread_id:'server-run', query:'恢复的诊断', status:'completed', updated_at:'2026-11-18T15:00:00Z'});
  wrapper = mount(DiagnosisHistory);
  await flushPromises();
  expect(wrapper.text()).toContain('恢复的诊断');
  expect(localStorage.getItem('aiops:runs:v2:7')).toContain('server-run');
});

it('retries the failed history page while preserving the pages already read', async () => {
  localStorage.clear();
  const { request } = await import('../lib/api');
  const calls = [];
  request.mockImplementation(async (path, options) => {
    if (path !== '/aiops/runs') return {status:'completed'};
    const offset = options.query.before_id ?? 0;
    calls.push(offset);
    if (offset === 200 && calls.filter(value => value === 200).length === 1)
      throw new Error('历史暂不可读取');
    return {
      next_before_id: offset === 200 ? null : offset + 100,
      runs: Array.from({length: offset === 200 ? 1 : 100}, (_, index) => ({
        thread_id: `page-${offset + index}`, query: `诊断记录 ${offset + index}`,
      })),
    };
  });
  wrapper = mount(DiagnosisHistory);
  await flushPromises();
  const button = (text) => wrapper.findAll('button').find(item => item.text() === text);
  await button('从服务器加载更早记录').trigger('click');
  await flushPromises();
  await button('从服务器加载更早记录').trigger('click');
  await flushPromises();
  expect(wrapper.text()).toContain('已加载 200 条');
  await button('重试加载更早记录').trigger('click');
  await flushPromises();
  expect(calls).toEqual([0, 100, 200, 200]);
  expect(wrapper.text()).toContain('已加载 201 条');
  await wrapper.get('input[type="search"]').setValue('诊断记录 200');
  expect(wrapper.text()).toContain('诊断记录 200');
});

it('retries a cached row detail when its server page is reached', async () => {
  localStorage.clear();
  rememberRun(7,{thread_id:'older-page',query:'本地记录',status:'running'});
  const { request } = await import('../lib/api');
  let details = 0;
  request.mockImplementation(async (path, options) => {
    if (path !== '/aiops/runs') {
      if (++details === 1) throw new Error('暂读不到详情');
      return {status:'completed', diagnosis:{kind:'localized_fault'}};
    }
    return options.query.before_id
      ? {runs:[{thread_id:'older-page', query:'较早的历史', status:'running'}]}
      : {runs:[], next_before_id:100};
  });
  wrapper = mount(DiagnosisHistory);
  await flushPromises();
  expect(wrapper.text()).toContain('状态未核实');
  await wrapper.findAll('button').find(button => button.text() === '从服务器加载更早记录').trigger('click');
  await flushPromises();
  expect(details).toBe(2);
  expect(wrapper.text()).toContain('故障层已定位');
  expect(wrapper.text()).not.toContain('状态未核实');
});
