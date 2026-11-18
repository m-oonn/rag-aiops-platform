<script setup>
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { request } from "../lib/api";
import {
  confirmAction,
  fail,
  notify,
  useLoad,
  dateTime,
  docStatus,
  tone,
} from "../lib/ui";
import PageHeader from "../components/PageHeader.vue";
import Feedback from "../components/Feedback.vue";
import DataTable from "../components/DataTable.vue";
import Icon from "../components/Icon.vue";
const route = useRoute(),
  router = useRouter(),
  rows = ref([]),
  selected = ref([]),
  filter = computed(
    () =>
      ({
        FAILURE: "failed",
        STARTED: "processing",
        PROCESSING: "processing",
        PENDING: "pending",
      })[route.query.status] ||
      route.query.status ||
      "",
  );
const statuses = [
  ["", "全部"],
  ["processing", "处理中"],
  ["pending", "待处理"],
  ["failed", "失败"],
];
const visible = computed(() =>
  rows.value.filter(
    (row) =>
      !filter.value ||
      (
        {
          processing: ["PROCESSING", "STARTED", "RETRY"],
          pending: ["PENDING"],
          failed: ["FAILURE"],
        }[filter.value] || []
      ).includes(String(row.status)),
  ),
);
const { loading, error, refresh } = useLoad(
  async () => {
    rows.value = await request("/monitor/", {
      query: { status_filter: filter.value },
    });
  },
  { interval: 15000 },
);
async function remove(row) {
  if (
    !(await confirmAction(
      "删除文档任务",
      `删除“${row.filename}”？`,
      "删除",
      true,
    ))
  )
    return;
  try {
    await request(`/monitor/tasks/${encodeURIComponent(row.doc_id)}`, {
      method: "DELETE",
    });
    await refresh();
    notify("任务已删除");
  } catch (e) {
    fail(e);
  }
}
async function batchDelete() {
  if (
    !selected.value.length ||
    !(await confirmAction(
      "删除文档任务",
      `删除 ${selected.value.length} 个任务？`,
      "删除",
      true,
    ))
  )
    return;
  try {
    await request("/monitor/tasks/batch-delete", {
      method: "POST",
      body: { task_ids: selected.value.map(String) },
    });
    selected.value = [];
    await refresh();
  } catch (e) {
    fail(e);
  }
}
watch(filter, () => {
  selected.value = [];
  refresh();
});
function setStatus(value) {
  router.replace({ query: value ? { status: value } : {} });
}
</script>
<template>
  <div class="page">
    <PageHeader title="文档任务"
      ><button class="button" :disabled="loading" @click="refresh()">
        <Icon name="refresh" :size="16" />刷新
      </button></PageHeader
    >
    <nav class="tabs">
      <button
        v-for="item in statuses"
        :key="item[0]"
        :class="{ active: filter === item[0] }"
        @click="setStatus(item[0])"
      >
        {{ item[1] }}
      </button>
    </nav>
    <div class="toolbar">
      <span class="muted">{{ visible.length }} 项</span
      ><button
        v-if="selected.length"
        class="button danger"
        @click="batchDelete"
      >
        删除 {{ selected.length }} 项
      </button>
    </div>
    <Feedback
      :loading="loading"
      :error="error"
      :empty="!visible.length && !loading"
      text="暂无任务"
      @retry="refresh()"
    /><DataTable
      v-if="visible.length"
      v-model="selected"
      :rows="visible"
      selectable
      row-key="doc_id"
      :columns="[
        { key: 'filename', label: '文档', width: '30%' },
        { key: 'kb_name', label: '知识库' },
        { key: 'status', label: '状态' },
        { key: 'progress', label: '进度' },
        { key: 'message', label: '错误信息', width: '24%' },
        { key: 'created_at', label: '创建时间' },
        { key: 'actions', label: '' },
      ]"
      ><template #filename="{ row }"
        ><div class="cell-title">
          <Icon name="file" /><strong>{{ row.filename }}</strong>
        </div></template
      ><template #status="{ row }"
        ><span :class="['status', tone(row.status)]">{{
          docStatus(row.status)
        }}</span></template
      ><template #progress="{ row }"
        ><div
          v-if="
            ['PENDING', 'PROCESSING', 'STARTED', 'RETRY'].includes(row.status)
          "
          class="progress-line"
        >
          <progress :value="row.progress || 0" max="100" /><span
            >{{ row.progress || 0 }}%</span
          >
        </div>
        <span v-else>{{
          row.status === "SUCCESS" ? "100%" : "—"
        }}</span></template
      ><template #message="{ row }"
        ><span class="truncate" :title="row.message || ''">{{
          row.message || "—"
        }}</span></template
      ><template #created_at="{ row }">{{ dateTime(row.created_at) }}</template
      ><template #actions="{ row }"
        ><button class="text-button danger" @click="remove(row)">
          删除
        </button></template
      ></DataTable
    >
  </div>
</template>
