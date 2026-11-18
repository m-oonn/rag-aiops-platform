<script setup>
import { computed, onUnmounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { request } from "../lib/api";
import { getHistory, rememberRun, validRunId, forgetRun } from "../lib/history";
import { confirmAction, dateTime, runStatus, tone } from "../lib/ui";
import { session } from "../lib/session";
import PageHeader from "../components/PageHeader.vue";
import DataTable from "../components/DataTable.vue";
import Feedback from "../components/Feedback.vue";
import Icon from "../components/Icon.vue";
import { reportOverview } from "../lib/diagnosisVisuals";
const rows = ref([]),
  query = ref(""),
  loading = ref(false),
  error = ref("");
const filtered = computed(() =>
  rows.value.filter((row) =>
    `${row.query || ""} ${row.thread_id}`
      .toLowerCase()
      .includes(query.value.toLowerCase()),
  ),
);
let version = 0;
async function load() {
  const current = ++version, userId = session.user?.id;
  loading.value = true;
  error.value = "";
  try {
    const saved = getHistory(userId);
    rows.value = saved;
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
        rows.value[index] = {
          ...saved[i],
          ...result.value,
          query: result.value.query || saved[i].query || "",
          readError: "",
        };
        rememberRun(userId, rows.value[index]);
      } else rows.value[index] = { ...saved[i], readError: result.reason.message };
    });
    rows.value = rows.value.filter((row) => validRunId(row.thread_id));
  } catch (e) {
    if (current === version) error.value = e.message;
  } finally {
    if (current === version) loading.value = false;
  }
}
watch(() => session.user?.id, () => { rows.value = []; load(); }, { immediate: true });
onUnmounted(() => { version++; });
async function remove(id) {
  const userId = session.user?.id;
  if (
    !(await confirmAction(
      "移除诊断记录",
      "只从此浏览器移除记录，不会删除服务器诊断。",
      "移除",
    ))
  )
    return;
  if (userId !== session.user?.id) return;
  try {
    forgetRun(userId, id);
    rows.value = rows.value.filter((row) => row.thread_id !== id);
  } catch { error.value = "浏览器未能保存移除操作，请检查存储权限后重试"; }
}
</script>
<template>
  <div class="page">
    <PageHeader title="最近诊断"
      ><RouterLink to="/aiops?new=1" class="button primary"
        ><Icon name="plus" :size="18" />新建诊断</RouterLink
      ></PageHeader
    >
    <div class="toolbar">
      <label class="search-input"
        ><Icon name="search" /><input
          v-model="query"
          placeholder="搜索诊断现象或编号"
          aria-label="搜索诊断" /></label
      ><button class="button" :disabled="loading" @click="load">
        <Icon name="refresh" :size="16" />刷新
      </button>
    </div>
    <Feedback
      :loading="loading"
      :error="error"
      :empty="!filtered.length && !loading"
      text="暂无诊断记录"
      @retry="load"
    /><DataTable
      v-if="filtered.length"
      :rows="filtered"
      row-key="thread_id"
      :columns="[
        { key: 'query', label: '诊断内容', width: '42%' },
        { key: 'status', label: '状态' },
        { key: 'diagnosis', label: '结论', width: '28%' },
        { key: 'updated_at', label: '最近更新' },
        { key: 'actions', label: '' },
      ]"
      ><template #query="{ row }"
        ><div class="cell-title">
          <Icon name="pulse" />
          <div>
            <RouterLink
              :to="{ path: '/aiops', query: { run: row.thread_id } }"
              class="text-button"
              >{{ row.query || "未命名诊断" }}</RouterLink
            ><details class="cell-subtitle"><summary>诊断编号</summary>{{ row.thread_id }}</details>
          </div>
        </div></template
      ><template #status="{ row }"
        ><span v-if="row.readError" class="text-danger" role="alert">状态未核实：{{ row.readError }}</span><span v-else :class="['status', tone(row.status)]">{{
          runStatus(row.status)
        }}</span></template
      ><template #diagnosis="{ row }">{{
        row.diagnosis ? reportOverview(row.diagnosis).title : "尚无诊断结论"
      }}</template
      ><template #updated_at="{ row }">{{ dateTime(row.updated_at) }}</template
      ><template #actions="{ row }"
        ><div class="actions">
          <RouterLink
            :to="{ path: '/aiops', query: { run: row.thread_id } }"
            class="text-button"
            >打开</RouterLink
          ><button class="text-button danger" @click="remove(row.thread_id)">
            移除
          </button>
        </div></template
      ></DataTable
    >
  </div>
</template>
