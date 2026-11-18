import { mount } from "@vue/test-utils";
import { expect, it } from "vitest";
import Markdown from "./Markdown.vue";

it("sanitizes untrusted markdown and emits an evidence selection", async () => {
  const wrapper = mount(Markdown, {
    props: {
      content:
        "<script>alert(1)</script><img src=x onerror=alert(1)>[unsafe](javascript:alert(1))\n\nev-0123456789abcdef",
    },
  });
  expect(wrapper.find("script").exists()).toBe(false);
  expect(wrapper.find("img").exists()).toBe(false);
  expect(wrapper.html()).not.toContain('href="javascript:');
  await wrapper.get("button").trigger("click");
  expect(wrapper.emitted("evidence")).toEqual([["ev-0123456789abcdef"]]);
  wrapper.unmount();
});
