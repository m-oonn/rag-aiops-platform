<script setup>
import { computed, onUnmounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { request } from "../lib/api";
import { getHistory, rememberRun, mergeHistoryRun, markHistoryRunUnavailable, mergeHistoryList, forgetRun } from "../lib/history";
import { confirmAction, dateTime, runStatus, tone } from "../lib/ui";
import { session } from "../lib/session";
import PageHeader from "../components/PageHeader.vue";
import DataTable from "../components/DataTable.vue";
import Feedback from "../components/Feedback.vue";
import Icon from "../components/Icon.vue";
import InsightBreakdown from "../components/InsightBreakdown.vue";
import { breakdown } from "../lib/breakdown";
import { reportOverview } from "../lib/diagnosisVisuals";
const rows = ref([]),
  query = ref(""),
  statusFilter = ref(""),
  loading = ref(false),
  loadingMore = ref(false),
  nextBeforeId = ref(null),
  nextPageError = ref(""),
  error = ref("");
const PAGE_SIZE = 100;
const matchQuery = computed(() => query.value.trim().toLowerCase());
const hasFilter = computed(() => Boolean(matchQuery.value || statusFilter.value));
const historyKey = row => row.readError ? 'read-error' : row.status || 'unknown';
const historyChart = computed(() => breakdown(rows.value, historyKey,
  key => key === 'read-error' ? '状态未核实' : key === 'unknown' ? '状态未知' : runStatus(key), tone));
const filtered = computed(() => rows.value.filter(row =>
  (!statusFilter.value || historyKey(row) === statusFilter.value) &&
  ((row.query || "").toLowerCase().includes(matchQuery.value) || row.thread_id.toLowerCase().includes(matchQuery.value)),
));
function clearFilters() { query.value = ""; statusFilter.value = ""; }
let version = 0;
async function load() {
  const current = ++version, userId = session.user?.id;
  nextBeforeId.value = null;
  loadingMore.value = false;
  nextPageError.value = "";
  loading.value = true;
  error.value = "";
  try {
    let saved;
    try {
      const result = await request("/aiops/runs", { query: { limit: PAGE_SIZE, stable_order: true } });
      if (current !== version || userId !== session.user?.id) return;
      const page = Array.isArray(result?.runs) ? result.runs : [];
      saved = mergeHistoryList(getHistory(userId), page, userId, Number.MAX_SAFE_INTEGER);
      nextBeforeId.value = result.next_before_id;
      rows.value = saved;
      saved.forEach(row => rememberRun(userId, row));
    } catch (e) {
      if (current !== version || userId !== session.user?.id) return;
      saved = getHistory(userId);
      rows.value = saved;
      error.value = `服务器历史暂不可读取，显示此浏览器已保存的记录：${e.message}`;
    }
    const settled = await Promise.allSettled(
      saved.map((row) =>
        request(`/aiops/runs/${encodeURIComponent(row.thread_id)}`),
      ),
    );
    if (current !== version || userId !== session.user?.id) return;
    settled.forEach((result, i) => {
      const index = rows.value.findIndex(row => row.thread_id === saved[i].thread_id);
      if (index < 0) return;
      if (result.status === "fulfilled") {
        rows.value[index] = mergeHistoryRun(saved[i], result.value);
        rememberRun(userId, rows.value[index]);
      } else rows.value[index] = markHistoryRunUnavailable(saved[i], result.reason);
    });
    rows.value = mergeHistoryList(rows.value, null, userId, Number.MAX_SAFE_INTEGER);
  } catch (e) {
    if (current === version) error.value = e.message;
  } finally {
    if (current === version) loading.value = false;
  }
}
async function loadMore() {
  if (!nextBeforeId.value || loadingMore.value || loading.value) return;
  const current = version, userId = session.user?.id, beforeId = nextBeforeId.value;
  loadingMore.value = true;
  nextPageError.value = "";
  try {
    const result = await request("/aiops/runs", { query: { limit: PAGE_SIZE, before_id: beforeId, stable_order: true } });
    if (current !== version || userId !== session.user?.id) return;
    const page = Array.isArray(result?.runs) ? result.runs : [];
    const pageIds = new Set(page.map(row => row?.thread_id));
    rows.value = mergeHistoryList(rows.value, page, userId, Number.MAX_SAFE_INTEGER);
    const pageRows = rows.value.filter(row => pageIds.has(row.thread_id));
    nextBeforeId.value = result.next_before_id;
    const settled = await Promise.allSettled(pageRows.map(row =>
      request(`/aiops/runs/${encodeURIComponent(row.thread_id)}`),
    ));
    if (current !== version || userId !== session.user?.id) return;
    settled.forEach((item, index) => {
      const rowIndex = rows.value.findIndex(row => row.thread_id === pageRows[index].thread_id);
      if (rowIndex < 0) return;
      if (item.status === "fulfilled") {
        rows.value[rowIndex] = mergeHistoryRun(rows.value[rowIndex], item.value);
        rememberRun(userId, rows.value[rowIndex]);
      } else rows.value[rowIndex] = markHistoryRunUnavailable(rows.value[rowIndex], item.reason);
    });
    rows.value = mergeHistoryList(rows.value, null, userId, Number.MAX_SAFE_INTEGER);
  } catch (e) {
    if (current === version && userId === session.user?.id)
      nextPageError.value = `更多历史暂不可读取，已保留当前记录：${e.message}`;
  } finally {
    if (current === version) loadingMore.value = false;
  }
}
watch(() => session.user?.id, () => { rows.value = []; clearFilters(); load(); }, { immediate: true });
onUnmounted(() => { version++; });
const removing = ref(false), notice = ref("");
async function remove(row) {
  if (removing.value) return;
  const id = row.thread_id;
  removing.value = true;
  const userId = session.user?.id;
  try {
    if (!(await confirmAction("从本机列表隐藏", `「${row.query?.slice(0, 60) || id}」仅从此浏览器的列表隐藏，不会删除服务器诊断。`,
      "隐藏", true, "aiops-confirm")) || userId !== session.user?.id) return;
    forgetRun(userId, id);
    rows.value = rows.value.filter(item => item.thread_id !== id);
  } catch { notice.value = "浏览器未能保存隐藏操作；诊断未被移除。"; }
  finally { removing.value = false; }
}
</script>
<template>
  <div class="page history-page">
    <PageHeader title="最近诊断"><RouterLink to="/aiops?new=1" class="button primary"><Icon name="plus" :size="18" />新建诊断</RouterLink></PageHeader>
    <div class="toolbar history-toolbar" aria-label="筛选和刷新诊断记录">
      <div class="history-filters">
        <label class="search-input"><Icon name="search" /><input v-model="query" type="search"
          placeholder="搜索已加载诊断" aria-label="搜索诊断" /></label>
        <select v-model="statusFilter" aria-label="按诊断状态筛选">
          <option value="">全部状态</option>
          <option v-if="statusFilter && !historyChart.some(item => item.key === statusFilter)" :value="statusFilter">{{ runStatus(statusFilter) }}</option>
          <option v-for="item in historyChart" :key="item.key" :value="item.key">{{ item.label }}</option>
        </select>
        <button v-if="hasFilter" class="text-button" @click="clearFilters">清除筛选</button>
      </div>
      <button class="button" :disabled="loading || loadingMore" @click="load"><Icon name="refresh" :size="16" />{{ loading ? '正在刷新…' : '刷新列表' }}</button>
    </div>
    <p v-if="notice" role="alert">{{ notice }}</p>
    <Feedback v-if="error" :error="error" @retry="load" />
    <Feedback v-else-if="loading && !rows.length" :loading="true" />
    <InsightBreakdown v-if="!error" v-model="statusFilter" :items="historyChart" title="诊断状态分布" icon="history"
      description="只统计已加载的记录；点击状态筛选下方列表。" variant="composition" unit="场" />
    <section :aria-busy="loading || loadingMore" aria-label="诊断记录列表">
      <p v-if="rows.length || hasFilter" class="history-count muted" role="status">{{ hasFilter ? `匹配 ${filtered.length} 条 · ` : '' }}已加载 {{ rows.length }} 条</p>
      <div v-if="!filtered.length && !loading" class="empty-state">
        <p>{{ hasFilter ? '已加载的记录中没有匹配项' : error ? '此浏览器没有可显示的记录' : '暂无诊断记录' }}</p>
        <button v-if="hasFilter" class="text-button" @click="clearFilters">查看全部已加载记录</button>
        <RouterLink v-else-if="!error && !nextBeforeId" to="/aiops?new=1" class="text-button">新建诊断</RouterLink>
      </div>
      <DataTable v-else-if="filtered.length" :key="JSON.stringify([matchQuery, statusFilter])" :rows="filtered" row-key="thread_id" pagination-label="已加载结果 · "
        :columns="[{ key: 'query', label: '故障现象', width: '42%' }, { key: 'status', label: '状态' }, { key: 'diagnosis', label: '结论', width: '28%' }, { key: 'updated_at', label: '最近更新' }, { key: 'actions', label: '操作' }]">
        <template #query="{ row }">
          <div class="cell-title history-title">
            <RouterLink :to="{ path: '/aiops', query: { run: row.thread_id } }" class="text-button">{{ row.query || '未命名诊断' }}</RouterLink>
            <details class="cell-subtitle"><summary>诊断编号</summary><code>{{ row.thread_id }}</code></details>
          </div>
        </template>
        <template #status="{ row }">
          <details v-if="row.readError" class="history-read-error"><summary>状态未核实</summary>{{ row.readError }}</details>
          <span v-else :class="['status', tone(row.status)]">{{ runStatus(row.status) }}</span>
        </template>
        <template #diagnosis="{ row }">{{ row.details_status === 'missing' ? '没有保存结构化详情' : row.details_status === 'unavailable' ? '详情暂不可读' : row.status === 'pending_review' ? '报告待复核' : row.status !== 'completed' ? '—' : row.diagnosis ? reportOverview(row.diagnosis).title : '尚无结构化结论' }}</template>
        <template #updated_at="{ row }"><time v-if="row.updated_at" :datetime="row.updated_at">{{ dateTime(row.updated_at) }}</time><span v-else>—</span></template>
        <template #actions="{ row }"><button class="text-button" :disabled="removing" :aria-label="`从本机隐藏：${row.query || row.thread_id}`" @click="remove(row)">本机隐藏</button></template>
      </DataTable>
    </section>
    <div v-if="nextBeforeId" class="history-pagination">
      <p v-if="nextPageError" role="alert">{{ nextPageError }}</p>
      <button class="button" :disabled="loadingMore || loading" @click="loadMore">{{ loadingMore ? '正在加载…' : nextPageError ? '重试加载更早记录' : '从服务器加载更早记录' }}</button>
    </div>
  </div>
</template>

<style scoped>
.history-toolbar, .history-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.history-filters { min-width: 0; }
.history-filters .search-input { width: min(320px, 100%); }
.history-filters select { min-height: 38px; font: inherit; border: 1px solid var(--line); background: white; padding: 0 8px; }
.history-count { margin: 0 0 12px; }
.history-title { display: block; min-width: 0; overflow-wrap: anywhere; }
.history-title .text-button { display: inline; white-space: pre-wrap; text-align: left; }
.history-read-error { color: var(--muted); overflow-wrap: anywhere; }
.history-read-error summary { width: max-content; cursor: pointer; }
.history-pagination { border-top: 1px solid var(--line); padding-top: 16px; margin-top: 16px; }
.history-page time, .history-page :deep(td.align-right) { white-space: nowrap; }
</style>
