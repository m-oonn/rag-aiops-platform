<script setup>
import { onUnmounted, ref, watch } from "vue";
import { request } from "../lib/api";
import FilePreview from "./FilePreview.vue";
import Modal from "./Modal.vue";
const props = defineProps({ references: { type: Array, default: () => [] } });
const active = ref(null), original = ref(null), preview = ref(null);
const chunkState = ref('idle'), previewState = ref('idle'), chunkError = ref(''), previewError = ref('');
let version = 0;
const title = row => `${row.source}${row.page ? ` · 第 ${row.page} 页` : ""}`;
function close() {
  version++;
  active.value = null;
  preview.value = null;
  original.value = null;
  chunkState.value = 'idle';
  previewState.value = 'idle';
}
function openOriginal(row) {
  if (!Number.isInteger(row.doc_id) || row.doc_id <= 0) return;
  close();
  active.value = row;
  readChunk();
  readPreview();
}
async function readChunk() {
  const row = active.value, current = version;
  if (!row || chunkState.value === 'loading') return;
  chunkState.value = 'loading';
  try {
    const chunks = await request(`/knowledge-bases/documents/${row.doc_id}/chunks`, { query: { chunk_uid: row.chunk_id, limit: 1 } });
    if (current !== version) return;
    original.value = (chunks.chunks || chunks).find(chunk => chunk.chunk_uid === row.chunk_id) || null;
    chunkState.value = 'ready';
  } catch (e) {
    if (current === version) { chunkError.value = e.message; chunkState.value = 'error'; }
  }
}
async function readPreview() {
  const row = active.value, current = version;
  if (!row || previewState.value === 'loading') return;
  previewState.value = 'loading';
  try {
    const blob = await request(`/knowledge-bases/documents/${row.doc_id}/preview`, { blob: true });
    if (current !== version) return;
    preview.value = blob; previewState.value = 'ready';
  } catch (e) {
    if (current === version) { previewError.value = e.message; previewState.value = 'error'; }
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
      <template v-if="active">
        <div class="reference-comparison">
          <section><h3>本轮保留的片段</h3><p class="excerpt-content">{{ active.content }}</p><small v-if="active.truncated">保留片段已截短</small></section>
          <section><h3>当前文档中的对应片段</h3>
            <p v-if="chunkState === 'loading'" role="status">正在读取对应片段…</p>
            <p v-else-if="chunkState === 'error'" role="alert">对应文字读取失败：{{ chunkError }} <button class="text-button" @click="readChunk">重试片段</button></p>
            <p v-else-if="original" class="excerpt-content">{{ original.content }}</p>
            <p v-else>当前文档中未找到本轮片段，尚不能完成逐段核对。</p>
          </section>
        </div>
        <section class="reference-preview"><h3>当前文档预览</h3>
          <p v-if="previewState === 'loading'" role="status">正在读取文档预览…</p>
          <p v-else-if="previewState === 'error'" role="alert">文档预览读取失败：{{ previewError }} <button class="text-button" @click="readPreview">重试预览</button></p>
          <FilePreview v-else-if="preview" :blob="preview" :filename="active.source" />
        </section>
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
.reference-comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
.reference-comparison section + section { border-inline-start: 1px solid var(--line); padding-inline-start: 20px; }
.reference-comparison .excerpt-content { max-height: 35vh; overflow: auto; }
.reference-preview { border-top: 1px solid var(--line); margin-top: 16px; padding-top: 16px; }
@media (max-width: 700px) {
  .reference-comparison { grid-template-columns: minmax(0, 1fr); }
  .reference-comparison section + section { border-inline-start: 0; padding-inline-start: 0; }
}
</style>
