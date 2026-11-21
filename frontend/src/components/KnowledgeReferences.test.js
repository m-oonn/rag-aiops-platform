import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import KnowledgeReferences from "./KnowledgeReferences.vue";
const request = vi.hoisted(() => vi.fn());
vi.mock("../lib/api", () => ({ request }));
let wrapper;
const reference = { doc_id: 34, chunk_id: "chunk-101", source: "手册.pdf", content: "历史片段" };
beforeEach(() => request.mockReset());
afterEach(() => wrapper?.unmount());
async function open() {
  wrapper = mount(KnowledgeReferences, { props: { references: [reference] }, global: { stubs: {
    Modal: { props: ["modelValue"], template: '<div v-if="modelValue" role="dialog"><slot /></div>' },
    FilePreview: { template: '<div>文档预览可读</div>' },
  } } });
  await wrapper.get(".reference-actions button").trigger("click");
  await flushPromises();
}
it("keeps readable text when preview fails and permits retry", async () => {
  request.mockImplementation(path => path.endsWith("/chunks")
    ? Promise.resolve([{ chunk_uid: reference.chunk_id, content: "完整对应文字" }])
    : Promise.reject(new Error("预览暂不可用")));
  await open();
  expect(wrapper.get('[role="dialog"]').text()).toContain("完整对应文字");
  expect(wrapper.get('[role="alert"]').text()).toContain("文档预览读取失败");
  await wrapper.setProps({ references: [{ ...reference }] });
  expect(wrapper.get('[role="dialog"]').text()).toContain("完整对应文字");
  request.mockImplementation(path => path.endsWith("/chunks")
    ? Promise.resolve([{ chunk_uid: reference.chunk_id, content: "完整对应文字" }])
    : Promise.resolve(new Blob(["PDF"])));
  await wrapper.get('[role="alert"] button').trigger("click");
  await flushPromises();
  expect(wrapper.find('[role="alert"]').exists()).toBe(false);
  expect(wrapper.get('[role="dialog"]').text()).toContain("历史片段");
  expect(request.mock.calls.filter(([path]) => path.endsWith("/chunks"))).toHaveLength(1);
  expect(wrapper.get('[role="dialog"]').text()).toContain("文档预览可读");
});
it("keeps the document preview when text fails without claiming the chunk is missing", async () => {
  request.mockImplementation(path => path.endsWith("/chunks")
    ? Promise.reject(new Error("文字暂不可读")) : Promise.resolve(new Blob(["PDF"])));
  await open();
  expect(wrapper.get('[role="dialog"]').text()).toContain("文档预览可读");
  expect(wrapper.get('[role="alert"]').text()).toContain("对应文字读取失败");
  expect(wrapper.get('[role="dialog"]').text()).not.toContain("未找到本轮片段");
});
