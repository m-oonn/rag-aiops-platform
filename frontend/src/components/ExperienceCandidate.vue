<script setup>
import { computed, onUnmounted, ref, watch } from 'vue';
import { request } from '../lib/api';
import { session } from '../lib/session';
import { readExperienceDraft, writeExperienceDraft } from '../lib/history';
import { confirmAction, dateTime, tone } from '../lib/ui';
import Markdown from './Markdown.vue';
const props = defineProps({ threadId: String, status: String });
const candidate = ref(null), error = ref(''), libraryError = ref(''), loading = ref(false), busy = ref('');
const libraryLoading = ref(false), actionError = ref('');
const libraries = ref([]), kbId = ref(''), note = ref('');
let version = 0;
let draftOwner = null;
const isAdmin = computed(() => session.user?.role === 'admin');
const names = { pending: '待审核', published: '已发布', rejected: '已拒绝', withdrawn: '已撤回', publication_missing: '发布文档已移除' };
const actionNames = { generate: '生成经验候选', publish: '发布经验', reject: '拒绝候选', withdraw: '撤回经验' };
const canPublish = computed(() => ['pending', 'publication_missing'].includes(candidate.value?.status));
const root = () => '/aiops/runs/' + encodeURIComponent(props.threadId) + '/experience';
function restoreDraft() {
  if (draftOwner && draftOwner.userId === session.user?.id && draftOwner.runId === props.threadId
      && draftOwner.candidate.id === candidate.value?.id && draftOwner.candidate.version === candidate.value?.version
      && draftOwner.candidate.status === candidate.value?.status && isAdmin.value) return;
  draftOwner = null;
  kbId.value = ''; note.value = '';
  if (!isAdmin.value || !['pending', 'published', 'publication_missing'].includes(candidate.value?.status)) return;
  const saved = readExperienceDraft(session.user.id, props.threadId, candidate.value);
  kbId.value = saved?.kbId || ''; note.value = saved?.note || '';
  draftOwner = {userId:session.user.id, runId:props.threadId, candidate:{...candidate.value}};
}
async function loadLibraries(current = version) {
  if (libraryLoading.value || !isAdmin.value || !canPublish.value) return;
  libraryLoading.value = true; libraryError.value = '';
  try {
    const rows = await request('/knowledge-bases');
    if (current !== version) return;
    libraries.value = rows.filter(row => row.owner_id === session.user.id && row.chunking_config?.retrieval_mode === 'bm25');
    if (kbId.value && !libraries.value.some(row => String(row.id) === String(kbId.value))) kbId.value = '';
  } catch (e) { if (current === version) libraryError.value = e.message; }
  finally { if (current === version) libraryLoading.value = false; }
}
async function load(reset = false) {
  if (reset !== true && (busy.value || loading.value)) return;
  const current = ++version;
  if (reset === true) { draftOwner = null; candidate.value = null; libraries.value = []; kbId.value = ''; note.value = ''; }
  error.value = ''; libraryError.value = ''; actionError.value = '';
  busy.value = ''; loading.value = false; libraryLoading.value = false;
  if (!props.threadId || props.status !== 'completed') return;
  loading.value = true;
  try {
    const response = await request(root());
    if (current !== version) return;
    candidate.value = response.experience || null;
    restoreDraft();
    if (isAdmin.value && canPublish.value) void loadLibraries(current);
  } catch (e) { if (current === version) error.value = e.message; }
  finally { if (current === version) loading.value = false; }
}
async function mutate(action) {
  if (busy.value || loading.value || !props.threadId || props.status !== 'completed' || (action && (!isAdmin.value || !note.value.trim()))) return;
  if (action === 'publish' && (!canPublish.value || libraryLoading.value || libraryError.value || !libraries.value.some(row => String(row.id) === String(kbId.value)))) return;
  if (action === 'reject' && candidate.value?.status !== 'pending' || action === 'withdraw' && candidate.value?.status !== 'published') return;
  const current = version;
  if (['reject', 'withdraw'].includes(action)) {
    const label = actionNames[action];
    const consequence = action === 'reject' ? '拒绝后，本候选不会发布到知识库。' : '撤回后，这条经验将从知识检索中移除。';
    if (!await confirmAction(label, consequence, label, true, 'aiops-confirm') || current !== version || busy.value) return;
  }
  busy.value = action || 'generate'; actionError.value = '';
  try {
    const response = await request(root() + (action ? '/review' : ''), { method: 'POST',
      ...(action ? { body: { action, note: note.value.trim(), ...(action === 'publish' ? { kb_id: Number(kbId.value) } : {}) } } : {}) });
    if (current !== version) return;
    if (draftOwner) writeExperienceDraft(draftOwner.userId, draftOwner.runId, draftOwner.candidate, null);
    draftOwner = null;
    candidate.value = response.experience || null;
    restoreDraft();
    if (!action) await loadLibraries(current);
  } catch (e) { if (current === version) actionError.value = actionNames[action || 'generate'] + '失败：' + e.message; }
  finally { if (current === version) busy.value = ''; }
}
watch([kbId, note], () => {
  if (draftOwner) writeExperienceDraft(draftOwner.userId, draftOwner.runId, draftOwner.candidate, {kbId:kbId.value, note:note.value});
}, {flush:'sync'});
watch([() => props.threadId, () => props.status, () => session.user?.id, () => session.user?.role], () => load(true), { immediate: true, flush: 'sync' });
onUnmounted(() => { version++; draftOwner = null; });
</script>

<template>
  <section v-if="threadId && status === 'completed'" class="experience-candidate" aria-label="诊断经验审核" :aria-busy="Boolean(busy) || loading">
    <h3>经验复用</h3>
    <p class="muted">历史经验仅供排查参考，不是当前现场事实；审核发布后才进入知识检索。</p>
    <p v-if="loading" aria-live="polite">正在读取经验候选…</p>
    <div v-if="error" role="alert">{{ error }} <button class="text-button" :disabled="busy" @click="load">重新读取经验</button></div>
    <template v-if="!loading && (candidate || !error)">
      <template v-if="!candidate">
        <button class="button" :disabled="Boolean(busy)" @click="mutate()">{{ busy === 'generate' ? '正在生成…' : '生成经验候选' }}</button>
        <p v-if="actionError" role="alert">{{ actionError }}</p>
      </template>
      <template v-else>
        <p><span :class="['status', tone(candidate.status)]">{{ names[candidate.status] || candidate.status }}</span> · 版本 {{ candidate.version }} · {{ candidate.payload?.evidence?.length || 0 }} 条来源证据</p>
        <details><summary>候选正文与来源</summary>
          <p v-if="candidate.payload?.query"><strong>故障现象：</strong>{{ candidate.payload.query }}</p>
          <p v-if="candidate.payload?.scope?.target_ids?.length">来源目标：{{ candidate.payload.scope.target_ids.join('、') }}</p>
          <p v-if="candidate.payload?.limitations" class="muted">{{ candidate.payload.limitations }}</p>
          <Markdown v-if="candidate.payload?.report" :content="candidate.payload.report" plain-citations />
          <details><summary>技术追溯数据</summary><pre tabindex="0" aria-label="候选技术追溯数据">{{ JSON.stringify(candidate.payload, null, 2) }}</pre></details>
        </details>
        <details v-if="candidate.history?.length"><summary>审核与撤回记录</summary>
          <ol class="experience-history"><li v-for="(entry, index) in candidate.history" :key="index">
            <strong>{{ actionNames[entry.action] || entry.action }}</strong>
            <span v-if="entry.reviewed_at || entry.at" class="muted"> · {{ dateTime(entry.reviewed_at || entry.at) }}</span>
            <span v-if="entry.reviewer_id != null" class="muted"> · 审核人 #{{ entry.reviewer_id }}</span>
            <span v-if="entry.kb_id != null" class="muted"> · 知识库 #{{ entry.kb_id }}</span>
            <p v-if="entry.note">{{ entry.note }}</p>
          </li></ol>
        </details>
        <template v-if="isAdmin && (canPublish || candidate.status === 'published')">
          <div class="experience-form">
            <label v-if="canPublish" class="field">发布知识库<select v-model="kbId" :disabled="Boolean(busy) || libraryLoading || !!libraryError || !libraries.length"><option value="">{{ libraryLoading ? '正在读取知识库…' : '请选择知识库' }}</option><option v-for="kb in libraries" :key="kb.id" :value="kb.id">{{ kb.name }}</option></select></label>
            <p v-if="libraryError" role="alert">知识库读取失败：{{ libraryError }} <button class="text-button" :disabled="Boolean(busy)" @click="loadLibraries()">重新读取知识库</button></p>
            <p v-else-if="canPublish && !libraryLoading && !libraries.length" class="muted">暂无本人拥有的 BM25 知识库。<a href="/knowledge-bases" target="_blank" rel="noopener">打开知识库（新窗口）</a> <button class="text-button" :disabled="Boolean(busy)" @click="loadLibraries()">重新读取知识库</button></p>
            <label class="field">审核意见（必填）<textarea v-model="note" rows="2" maxlength="4000" :disabled="Boolean(busy)" /></label>
            <p v-if="actionError" role="alert">{{ actionError }}</p>
            <div class="actions">
              <button v-if="canPublish" class="button primary" :disabled="Boolean(busy) || !note.trim() || !kbId || libraryLoading || !!libraryError" @click="mutate('publish')">{{ busy === 'publish' ? '正在发布…' : candidate.status === 'publication_missing' ? '审核并补发' : '审核并发布' }}</button>
              <button v-if="candidate.status === 'pending'" class="button danger" :disabled="Boolean(busy) || !note.trim()" @click="mutate('reject')">{{ busy === 'reject' ? '正在拒绝…' : '拒绝候选' }}</button>
              <button v-if="candidate.status === 'published'" class="button danger" :disabled="Boolean(busy) || !note.trim()" @click="mutate('withdraw')">{{ busy === 'withdraw' ? '正在撤回…' : '撤回经验' }}</button>
            </div>
          </div>
        </template>
      </template>
    </template>
  </section>
</template>

<style scoped>
.experience-candidate { border-top: 1px solid var(--line); margin-top: 24px; padding-top: 16px; }
details, .field { margin: 12px 0; }
pre { max-height: 360px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
.experience-candidate { overflow-wrap: anywhere; }
.experience-form { max-width: 72ch; border-top: 1px solid var(--line); padding: 4px 0 0; }
.experience-form .actions { justify-content: flex-start; }
.experience-history li { padding-block: 4px; }
.experience-history p { margin: 4px 0 8px; white-space: pre-wrap; }
</style>
