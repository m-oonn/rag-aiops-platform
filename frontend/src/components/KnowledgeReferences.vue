<script setup>
import { onUnmounted, ref, watch } from "vue";
import { request } from "../lib/api";
import FilePreview from "./FilePreview.vue";
import Modal from "./Modal.vue";
const props = defineProps({ references: { type: Array, default: () => [] } });
const active = ref(null), original = ref(null), preview = ref(null), busy = ref(false), error = ref("");
let version = 0;
const title = row => `${row.source}${row.page ? ` · 第 ${row.page} 页` : ""}`;
function close() {
  version++;
  active.value = null;
  preview.value = null;
  original.value = null;
}
async function openOriginal(row) {
  if (!Number.isInteger(row.doc_id) || row.doc_id <= 0) return;
  const current = ++version;
  active.value = row;
  original.value = null;
  preview.value = null;
  error.value = "";
  busy.value = true;
  try {
    const [chunks, blob] = await Promise.all([
      request(`/knowledge-bases/documents/${row.doc_id}/chunks`, { query: { limit: 100 } }),
      request(`/knowledge-bases/documents/${row.doc_id}/preview`, { blob: true }),
    ]);
    if (current !== version) return;
    original.value = (chunks.chunks || chunks).find(chunk => chunk.chunk_uid === row.chunk_id) || null;
    preview.value = blob;
  } catch (e) {
    if (current === version) error.value = e.message;
  } finally {
    if (current === version) busy.value = false;
  }
}
watch(() => JSON.stringify(props.references), close);
onUnmounted(close);
</script>
<template>
  <section class="knowledge-references" aria-label="本轮知识参考">
    <details>
      <summary>本轮检索到的参考资料 · {{ references.length }} 段</summary>
      <p class="reference-boundary">仅供选择排查方法，不能证明当前故障。原因判断以上方现场证据为准。</p>
      <article v-for="(row, index) in references" :key="`${row.chunk_id}-${index}`" class="knowledge-excerpt">
        <h3>{{ title(row) }}</h3>
        <p class="excerpt-content">{{ row.content }}</p>
        <small v-if="row.truncated">片段已截短，可核对完整原文。</small>
        <div class="reference-actions">
          <button v-if="Number.isInteger(row.doc_id) && row.doc_id > 0" class="text-button" @click="openOriginal(row)">核对原文</button>
          <span v-else>该资料未提供原文入口</span>
          <details><summary>来源编号</summary><p>知识库：{{ row.kb_id || '未提供' }} · 文档：{{ row.doc_id || '未提供' }}</p><p>片段：{{ row.chunk_id || '未提供' }}</p></details>
        </div>
      </article>
    </details>
    <Modal :model-value="!!active" :title="active ? title(active) : '知识原文'" wide @update:model-value="!$event && close()">
      <p v-if="busy" role="status">正在读取有权限访问的原文…</p>
      <p v-else-if="error" role="alert">{{ error }} <button class="text-button" @click="openOriginal(active)">重试读取原文</button></p>
      <template v-else-if="active">
        <h3>当前文档中的对应片段</h3>
        <p v-if="original" class="excerpt-content">{{ original.content }}</p>
        <p v-else>当前文档中未找到本轮片段，尚不能完成逐段核对。可查看下面的原文确认文档是否已更新。</p>
        <p class="reference-boundary">此处展示当前有权读取的文档；本轮检索时的片段保留在报告中。</p>
        <FilePreview v-if="preview" :blob="preview" :filename="active.source" />
      </template>
    </Modal>
  </section>
</template>
<style scoped>
.knowledge-references { margin-top: 32px; border-top: 1px solid #e8e7e5; border-bottom: 1px solid #e8e7e5; padding: 18px 0; font-size: 13px; }
summary { cursor: pointer; color: #605e5c; }
.reference-boundary { color: #73716e; font-size: 12px; line-height: 1.8; }
.knowledge-excerpt { padding: 16px 0; border-top: 1px solid #edebe9; }
h3 { font-size: 14px; font-weight: 600; margin: 0 0 12px; }
.excerpt-content { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 13px; line-height: 1.9; }
small { display: block; color: #73716e; margin: 8px 0; }
.reference-actions { display: flex; flex-wrap: wrap; align-items: baseline; gap: 12px 24px; }
.reference-actions details { min-width: 0; color: #73716e; font-size: 12px; overflow-wrap: anywhere; }
</style>
