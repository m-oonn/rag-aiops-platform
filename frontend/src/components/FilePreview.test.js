import { afterEach, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import FilePreview from "./FilePreview.vue";

afterEach(() => vi.unstubAllGlobals());

it("offers the authorized PDF blob for download when embedded preview is unavailable", async () => {
  const createObjectURL = vi.fn(() => "blob:authorized-pdf");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
  const blob = new Blob(["original PDF bytes"], { type: "application/pdf" });
  const wrapper = mount(FilePreview, { props: { blob, filename: "排查手册.pdf" } });
  expect(createObjectURL).toHaveBeenCalledWith(blob);
  expect(wrapper.get("a").attributes()).toMatchObject({ href: "blob:authorized-pdf", download: "排查手册.pdf" });
  await wrapper.setProps({ blob: null });
  expect(wrapper.find("a").exists()).toBe(false);
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:authorized-pdf");
  wrapper.unmount();
});
