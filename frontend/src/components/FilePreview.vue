<script setup>
import { ref, watch, onUnmounted } from "vue";
import DOMPurify from "dompurify";
const props = defineProps({ blob: Object, filename: { type: String, default: "document.pdf" } });
const url = ref(""),
  text = ref(""),
  html = ref(""),
  type = ref("");
let version = 0;
function release() {
  if (url.value) URL.revokeObjectURL(url.value);
  url.value = "";
}
watch(
  () => props.blob,
  async (blob) => {
    const current = ++version;
    release();
    text.value = "";
    html.value = "";
    type.value = blob?.type || "";
    if (!blob) return;
    if (
      type.value === "application/pdf" ||
      /^image\/(png|jpeg|gif|webp|bmp)$/.test(type.value)
    )
      url.value = URL.createObjectURL(blob);
    else if (
      type.value.startsWith("text/") ||
      ["application/json", "application/xml"].includes(type.value)
    ) {
      const value = await blob.text();
      if (current !== version) return;
      if (type.value.includes("html"))
        html.value = DOMPurify.sanitize(value, {
          FORBID_TAGS: [
            "style",
            "script",
            "iframe",
            "object",
            "embed",
            "form",
            "img",
          ],
          FORBID_ATTR: ["style"],
        });
      else text.value = value;
    }
  },
  { immediate: true },
);
onUnmounted(() => {
  version++;
  release();
});
</script>
<template>
  <template v-if="url && type === 'application/pdf'">
    <p class="muted">若下方 PDF 为空白，可<a :href="url" :download="filename">下载 PDF 原文件</a>核对。</p>
    <object :data="url" type="application/pdf" class="document-preview">
      <p>当前浏览器无法预览 PDF，请下载查看。</p>
    </object>
  </template>
  <img v-else-if="url" :src="url" alt="文件预览" class="image-preview" />
  <div v-else-if="html" class="markdown" v-html="html" />
  <pre v-else-if="text">{{ text }}</pre>
  <div v-else class="empty-state compact">此文件暂不支持预览，请下载查看。</div>
</template>
