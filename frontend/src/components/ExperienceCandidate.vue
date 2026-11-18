<script setup>
import { computed, onUnmounted, ref, watch } from 'vue';
import { request } from '../lib/api';
import { session } from '../lib/session';
const props = defineProps({ threadId: String, status: String });
const candidate = ref(null), error = ref(''), libraryError = ref(''), loading = ref(false), busy = ref(false);
const libraries = ref([]), kbId = ref(''), note = ref('');
let version = 0;
const isAdmin = computed(() => session.user?.role === 'admin');
const names = { pending: '待审核', published: '已发布', rejected: '已拒绝', withdrawn: '已撤回' };
const root = () => '/aiops/runs/' + encodeURIComponent(props.threadId) + '/experience';
async function load(reset = false) {
  const current = ++version;
  if (reset === true) { candidate.value = null; libraries.value = []; kbId.value = ''; note.value = ''; }
  error.value = ''; libraryError.value = '';
  busy.value = false; loading.value = false;
  if (!props.threadId || props.status !== 'completed') return;
  loading.value = true;
  try {
    const response = await request(root());
    if (current !== version) return;
    candidate.value = response.experience || null;
    if (isAdmin.value && candidate.value?.status === 'pending') {
      try {
        const rows = await request('/knowledge-bases');
        if (current !== version) return;
        libraries.value = rows.filter(row => row.owner_id === session.user.id && row.chunking_config?.retrieval_mode === 'bm25');
      } catch (e) { if (current === version) libraryError.value = e.message; }
    }
  } catch (e) { if (current === version) error.value = e.message; }
  finally { if (current === version) loading.value = false; }
}
async function mutate(action) {
  if (busy.value || (action && (!isAdmin.value || !note.value.trim()))) return;
  const current = version;
  busy.value = true; error.value = '';
  try {
    const response = await request(root() + (action ? '/review' : ''), { method: 'POST',
      ...(action ? { body: { action, note: note.value.trim(), ...(action === 'publish' ? { kb_id: Number(kbId.value) } : {}) } } : {}) });
    if (current !== version) return;
    candidate.value = response.experience || null;
    note.value = '';
    if (!action) await load();
  } catch (e) { if (current === version) error.value = e.message; }
  finally { if (current === version) busy.value = false; }
}
watch([() => props.threadId, () => props.status, () => session.user?.id, () => session.user?.role], () => load(true), { immediate: true });
onUnmounted(() => { version++; });
</script>

<template>
  <section v-if="threadId && status === 'completed'" class="experience-candidate" aria-label="诊断经验审核">
    <h3>经验复用</h3>
    <p class="muted">历史经验仅供排查参考，不是当前现场事实；审核发布后才进入知识检索。</p>
    <p v-if="loading" aria-live="polite">正在读取经验候选…</p>
    <div v-if="error" role="alert">{{ error }} <button class="text-button" :disabled="busy" @click="load">重新读取经验</button></div>
    <template v-if="!loading && (candidate || !error)">
      <button v-if="!candidate" class="button" :disabled="busy" @click="mutate()">生成经验候选</button>
      <template v-else>
        <p>{{ names[candidate.status] || candidate.status }} · 版本 {{ candidate.version }} · {{ candidate.payload?.evidence?.length || 0 }} 条来源证据</p>
        <details><summary>候选正文与来源</summary><pre>{{ JSON.stringify(candidate.payload, null, 2) }}</pre></details>
        <details v-if="candidate.history?.length"><summary>审核与撤回记录</summary><pre>{{ JSON.stringify(candidate.history, null, 2) }}</pre></details>
        <template v-if="isAdmin && ['pending', 'published'].includes(candidate.status)">
          <label v-if="candidate.status === 'pending'" class="field">发布到自己的本地经验库<select v-model="kbId" :disabled="busy"><option value="">请选择知识库</option><option v-for="kb in libraries" :key="kb.id" :value="kb.id">{{ kb.name }}</option></select></label>
          <p v-if="libraryError" role="alert">{{ libraryError }} <button class="text-button" :disabled="busy" @click="load()">重新读取知识库</button></p>
          <p v-else-if="candidate.status === 'pending' && !libraries.length" class="muted">请先创建使用 BM25 的本地知识库。<a href="/knowledge-bases" target="_blank" rel="noopener">打开知识库</a> <button class="text-button" @click="load()">重新读取知识库</button></p>
          <label class="field">审核意见<textarea v-model="note" maxlength="4000" :disabled="busy" /></label>
          <template v-if="candidate.status === 'pending'">
            <button class="button primary" :disabled="busy || !note.trim() || !kbId" @click="mutate('publish')">审核并发布</button>
            <button class="button" :disabled="busy || !note.trim()" @click="mutate('reject')">拒绝候选</button>
          </template>
          <button v-else class="button" :disabled="busy || !note.trim()" @click="mutate('withdraw')">撤回经验</button>
        </template>
      </template>
    </template>
  </section>
</template>

<style scoped>
.experience-candidate { border-top: 1px solid var(--line); margin-top: 24px; padding-top: 16px; }
details, .field { margin: 12px 0; }
pre { max-height: 360px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
button + button { margin-left: 8px; }
</style>
