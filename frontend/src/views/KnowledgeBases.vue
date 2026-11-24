<script setup>
import { computed, reactive, ref } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { session } from "../lib/session";
import { request } from "../lib/api";
import { confirmAction, fail, notify, useLoad, dateTime } from "../lib/ui";
import PageHeader from "../components/PageHeader.vue";
import DataTable from "../components/DataTable.vue";
import Feedback from "../components/Feedback.vue";
import Modal from "../components/Modal.vue";
import Icon from "../components/Icon.vue";
import InsightBreakdown from "../components/InsightBreakdown.vue";
import { breakdown } from "../lib/breakdown";
const rows = ref([]),
  filter = ref(""),
  modal = ref(false),
  editing = ref(null),
  busy = ref(false);
const form = reactive({
  name: "",
  description: "",
  is_public: false,
  method: "recursive",
  chunk_size: 800,
  chunk_overlap: 120,
  retrieval_mode: "hybrid",
});
const accessFilter = ref('');
const accessKey = row => row.is_public ? 'public' : 'personal';
const accessChart = computed(() => breakdown(rows.value, accessKey,
  key => key === 'public' ? '公开知识库' : '个人知识库', key => key === 'public' ? 'info' : 'muted'));
const filtered = computed(() =>
  rows.value.filter((row) =>
    (!accessFilter.value || accessKey(row) === accessFilter.value) && `${row.name} ${row.description || ""}`
      .toLowerCase()
      .includes(filter.value.toLowerCase()),
  ),
);
const columns = [
  { key: "name", label: "知识库", width: "34%" },
  { key: "retrieval", label: "检索模式" },
  { key: "access", label: "访问权限" },
  { key: "created_at", label: "创建时间" },
  { key: "actions", label: "" },
];
const route = useRoute();
const canEdit = (row) => row.owner_id === session.user?.id;
async function load() {
  rows.value = await request("/knowledge-bases/");
  const row = rows.value.find((item) => String(item.id) === route.query.edit);
  if (row && canEdit(row)) open(row);
}
const { loading, error, refresh } = useLoad(load);
function open(row = null) {
  editing.value = row;
  const conf = row?.chunking_config || {};
  Object.assign(form, {
    name: row?.name || "",
    description: row?.description || "",
    is_public: row?.is_public || false,
    method: conf.method || "recursive",
    chunk_size: conf.chunk_size || 800,
    chunk_overlap: conf.chunk_overlap ?? 120,
    retrieval_mode: conf.retrieval_mode || "hybrid",
  });
  modal.value = true;
}
async function save() {
  if (!form.name.trim()) return fail(new Error("请填写知识库名称"));
  if (form.chunk_overlap >= form.chunk_size)
    return fail(new Error("重叠长度须小于分块长度"));
  busy.value = true;
  try {
    const body = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      is_public: form.is_public,
      chunking_config: {
        method: form.method,
        chunk_size: Number(form.chunk_size),
        chunk_overlap: Number(form.chunk_overlap),
        retrieval_mode: form.retrieval_mode,
      },
    };
    if (editing.value)
      await request(`/knowledge-bases/${editing.value.id}`, {
        method: "PUT",
        body,
      });
    else await request("/knowledge-bases/", { method: "POST", body });
    modal.value = false;
    await refresh();
    notify(editing.value ? "知识库已更新" : "知识库已创建");
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}
async function remove(row) {
  if (
    !(await confirmAction(
      "删除知识库",
      `删除“${row.name}”？此操作无法撤销。`,
      "删除",
      true,
    ))
  )
    return;
  try {
    await request(`/knowledge-bases/${row.id}`, { method: "DELETE" });
    await refresh();
    notify("知识库已删除");
  } catch (e) {
    fail(e);
  }
}
</script>
<template>
  <div class="page">
    <PageHeader title="知识库"
      ><button class="button" :disabled="loading" @click="refresh()">
        <Icon name="refresh" :size="16" />刷新</button
      ><button class="button primary" @click="open()">
        <Icon name="plus" :size="18" />新建知识库
      </button></PageHeader
    >
    <div class="toolbar">
      <label class="search-input"
        ><Icon name="search" :size="18" /><input
          v-model="filter"
          type="search"
          placeholder="搜索知识库"
          aria-label="搜索知识库" /></label
      ><span class="muted">{{ filtered.length }} 个知识库</span>
    </div>
    <InsightBreakdown v-if="!error" v-model="accessFilter" :items="accessChart" title="知识库访问范围" icon="book"
      description="只统计当前账号可见的知识库；点击查看对应清单。" variant="composition" unit="个" />
    <Feedback
      :loading="loading"
      :error="error"
      :empty="!filtered.length && !loading"
      @retry="refresh()"
      ><span>没有匹配的知识库</span
      ><button class="text-button" @click="filter = ''">
        清除搜索
      </button></Feedback
    ><DataTable v-if="filtered.length" :rows="filtered" :columns="columns"
      ><template #name="{ row }"
        ><div class="cell-title">
          <Icon name="book" />
          <div>
            <RouterLink
              :to="`/knowledge-bases/${row.id}`"
              class="text-button"
              >{{ row.name }}</RouterLink
            ><span v-if="row.description" class="cell-subtitle">{{
              row.description
            }}</span>
          </div>
        </div></template
      ><template #retrieval="{ row }"
        ><span class="tag">{{
          row.chunking_config?.retrieval_mode === "bm25" ? "关键词" : "混合检索"
        }}</span></template
      ><template #access="{ row }">{{
        row.is_public ? "公开" : "仅自己"
      }}</template
      ><template #created_at="{ row }">{{ dateTime(row.created_at) }}</template
      ><template #actions="{ row }"
        ><div class="actions">
          <button v-if="canEdit(row)" class="text-button" @click="open(row)">
            编辑</button
          ><button
            v-if="canEdit(row)"
            class="text-button danger"
            @click="remove(row)"
          >
            删除
          </button>
        </div></template
      ></DataTable
    ><Modal v-model="modal" :title="editing ? '编辑知识库' : '新建知识库'"
      ><form @submit.prevent="save">
        <label class="field"
          >名称<input
            v-model.trim="form.name"
            required
            maxlength="120" /></label
        ><label class="field"
          >描述<textarea
            v-model="form.description"
            rows="3"
            maxlength="1000"
          /></label
        ><label class="check-label"
          ><input
            v-model="form.is_public"
            type="checkbox"
          />允许其他用户使用</label
        >
        <div class="form-section">
          <h3>分块与检索</h3>
          <div class="field-grid">
            <label class="field"
              >分块方式<select v-model="form.method">
                <option value="recursive">递归分块</option>
                <option value="fixed">定长分块</option>
              </select></label
            ><label class="field"
              >检索模式<select v-model="form.retrieval_mode">
                <option value="hybrid">混合检索</option>
                <option value="bm25">关键词检索</option>
              </select></label
            ><label class="field"
              >分块长度<input
                v-model.number="form.chunk_size"
                type="number"
                min="100"
                max="10000"
                required /></label
            ><label class="field"
              >重叠长度<input
                v-model.number="form.chunk_overlap"
                type="number"
                min="0"
                :max="Math.max(0, form.chunk_size - 1)"
                required
            /></label>
          </div>
        </div>
        <div class="form-actions">
          <button type="button" class="button" @click="modal = false">
            取消</button
          ><button class="button primary" :disabled="busy">
            {{ busy ? "保存中…" : "保存知识库" }}
          </button>
        </div>
      </form></Modal
    >
  </div>
</template>
