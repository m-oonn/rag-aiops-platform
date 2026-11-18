<script setup>
import { computed, reactive, ref, watch } from "vue";
import { request, downloadBlob } from "../lib/api";
import {
  confirmAction,
  evalStatus,
  fail,
  notify,
  tone,
  useLoad,
  dateTime,
} from "../lib/ui";
import PageHeader from "../components/PageHeader.vue";
import Feedback from "../components/Feedback.vue";
import DataTable from "../components/DataTable.vue";
import Markdown from "../components/Markdown.vue";
import Modal from "../components/Modal.vue";
import Icon from "../components/Icon.vue";

const rows = ref([]);
const kbs = ref([]);
const documents = ref([]);
const selected = ref([]);
const filter = ref("");
const task = ref(null);
const items = ref([]);
const report = ref("");
const upload = ref(null);
const uploadExisting = ref(false);
const busy = ref(false);
const createOpen = ref(false);
const datasetOpen = ref(false);
const reportOpen = ref(false);
const editorOpen = ref(false);
const editingItem = ref(null);

const form = reactive({
  kb_id: "",
  num_questions: 10,
  mode: "kb",
  num_docs: 5,
  doc_ids: [],
  is_custom_upload: false,
});
const editForm = reactive({
  question: "",
  ground_truth: "",
  qa_type: "single_hop",
});
const visible = computed(() =>
  rows.value.filter((row) =>
    row.name.toLowerCase().includes(filter.value.toLowerCase()),
  ),
);
const dialogTitle = computed(() =>
  uploadExisting.value
    ? `上传数据集 · ${task.value?.name || ""}`
    : "新建评测任务",
);

watch(createOpen, (open) => {
  if (!open && uploadExisting.value) {
    uploadExisting.value = false;
    openDataset(task.value);
  }
});

const { loading, error, refresh } = useLoad(async () => {
  const result = await Promise.allSettled([
    request("/evaluations/tasks"),
    request("/knowledge-bases/"),
  ]);
  if (result[0].status === "rejected") throw result[0].reason;
  rows.value = result[0].value;
  kbs.value = result[1].status === "fulfilled" ? result[1].value : [];
});

function newTask() {
  task.value = null;
  uploadExisting.value = false;
  upload.value = null;
  Object.assign(form, {
    kb_id: "",
    num_questions: 10,
    mode: "kb",
    num_docs: 5,
    doc_ids: [],
    is_custom_upload: false,
  });
  createOpen.value = true;
}

async function loadDocs() {
  form.doc_ids = [];
  if (!form.kb_id) {
    documents.value = [];
    return;
  }
  try {
    documents.value = await request(`/knowledge-bases/${form.kb_id}/documents`);
  } catch (error) {
    fail(error);
  }
}

async function saveDatasetFile(target) {
  if (!upload.value) throw new Error("请选择数据集文件");
  const body = new FormData();
  body.append("file", upload.value);
  await request(`/evaluations/${target.id}/upload-dataset`, {
    method: "POST",
    body,
  });
  upload.value = null;
}

async function create() {
  if (uploadExisting.value) {
    if (
      !(await confirmAction(
        "上传评测数据集",
        `将数据集加入“${task.value.name}”？`,
        "上传",
      ))
    )
      return;
    busy.value = true;
    try {
      await saveDatasetFile(task.value);
      createOpen.value = false;
      uploadExisting.value = false;
      await openDataset(task.value);
      await refresh();
      task.value =
        rows.value.find((row) => row.id === task.value.id) || task.value;
      notify("数据集已上传");
    } catch (error) {
      fail(error);
    } finally {
      busy.value = false;
    }
    return;
  }

  busy.value = true;
  try {
    if (!form.is_custom_upload && !form.kb_id) throw new Error("请选择知识库");
    if (form.is_custom_upload && !upload.value)
      throw new Error("请选择数据集文件");
    if (form.mode === "doc" && !form.doc_ids.length)
      throw new Error("请选择至少一份文档");
    const config = {
      kb_id: form.kb_id ? Number(form.kb_id) : null,
      num_questions: Number(form.num_questions),
      mode: form.mode,
      num_docs: Number(form.num_docs),
      doc_ids: form.doc_ids.length ? form.doc_ids.map(Number) : null,
      is_custom_upload: form.is_custom_upload,
    };
    const created = await request("/evaluations/generate", {
      method: "POST",
      body: config,
    });
    if (form.is_custom_upload) await saveDatasetFile(created);
    createOpen.value = false;
    await refresh();
    if (form.is_custom_upload) await openDataset(created);
    notify("评测任务已创建");
  } catch (error) {
    fail(error);
  } finally {
    busy.value = false;
  }
}

function openDatasetUpload(row) {
  task.value = row;
  datasetOpen.value = false;
  upload.value = null;
  uploadExisting.value = true;
  form.is_custom_upload = true;
  createOpen.value = true;
}

async function openDataset(row) {
  task.value = row;
  datasetOpen.value = true;
  items.value = [];
  try {
    items.value = await request(`/evaluations/${row.id}/dataset`);
  } catch (error) {
    fail(error);
  }
}

function editItem(row) {
  editingItem.value = row;
  Object.assign(editForm, {
    question: row.question,
    ground_truth: row.ground_truth,
    qa_type: row.qa_type,
  });
  datasetOpen.value = false;
  editorOpen.value = true;
}

async function saveItem() {
  if (!editForm.question.trim() || !editForm.ground_truth.trim())
    return fail(new Error("问题和参考答案不能为空"));
  busy.value = true;
  try {
    await request(`/evaluations/dataset-items/${editingItem.value.id}`, {
      method: "PUT",
      body: { ...editForm },
    });
    editorOpen.value = false;
    await openDataset(task.value);
    notify("评测样本已保存");
  } catch (error) {
    fail(error);
  } finally {
    busy.value = false;
  }
}

async function removeItem(row) {
  if (!(await confirmAction("删除评测样本", "此操作无法撤销。", "删除", true)))
    return;
  try {
    await request(`/evaluations/dataset-items/${row.id}`, { method: "DELETE" });
    await openDataset(task.value);
    notify("评测样本已删除");
  } catch (error) {
    fail(error);
  }
}

async function run(row) {
  if (!row || row.status !== 4) return;
  if (
    !(await confirmAction(
      "开始评测",
      `使用“${row.name}”开始评测？`,
      "开始评测",
    ))
  )
    return;
  try {
    await request(`/evaluations/${row.id}/run`, { method: "POST" });
    notify("评测已开始");
    await refresh();
  } catch (error) {
    fail(error);
  }
}

async function showReport(row) {
  task.value = row;
  try {
    const result = await request(`/evaluations/${row.id}/report`);
    report.value = result.content || JSON.stringify(result, null, 2);
    reportOpen.value = true;
  } catch (error) {
    fail(error);
  }
}

async function removeSelected() {
  if (
    !selected.value.length ||
    !(await confirmAction(
      "删除评测任务",
      `删除 ${selected.value.length} 个任务？`,
      "删除",
      true,
    ))
  )
    return;
  try {
    await request("/evaluations/tasks/batch-delete", {
      method: "DELETE",
      body: selected.value,
    });
    selected.value = [];
    await refresh();
    notify("评测任务已删除");
  } catch (error) {
    fail(error);
  }
}

function downloadReport() {
  downloadBlob(
    new Blob([report.value], { type: "text/markdown" }),
    `${task.value?.name || "evaluation-report"}.md`,
  );
}
</script>

<template>
  <div class="page">
    <PageHeader title="效果评测">
      <button class="button" :disabled="loading" @click="refresh()">
        <Icon name="refresh" :size="16" />刷新
      </button>
      <button class="button primary" @click="newTask">
        <Icon name="plus" :size="16" />新建评测
      </button>
    </PageHeader>

    <div class="toolbar">
      <label class="search-input"
        ><Icon name="search" /><input
          v-model="filter"
          type="search"
          placeholder="搜索评测"
          aria-label="搜索评测"
      /></label>
      <button
        v-if="selected.length"
        class="button danger"
        @click="removeSelected"
      >
        删除 {{ selected.length }} 项
      </button>
    </div>
    <Feedback
      :loading="loading"
      :error="error"
      :empty="!visible.length && !loading"
      text="暂无评测任务"
      @retry="refresh()"
    />
    <DataTable
      v-if="visible.length"
      v-model="selected"
      :rows="visible"
      selectable
      :columns="[
        { key: 'name', label: '任务', width: '35%' },
        { key: 'status', label: '状态' },
        { key: 'progress', label: '进度' },
        { key: 'created_at', label: '创建时间' },
        { key: 'actions', label: '' },
      ]"
    >
      <template #name="{ row }"
        ><div class="cell-title">
          <Icon name="chart" /><strong>{{ row.name }}</strong>
        </div></template
      >
      <template #status="{ row }"
        ><span :class="['status', tone(row.status)]">{{
          evalStatus(row.status)
        }}</span></template
      >
      <template #progress="{ row }"
        >{{ row.completed_count || 0 }} / {{ row.total_count || 0 }}</template
      >
      <template #created_at="{ row }">{{ dateTime(row.created_at) }}</template>
      <template #actions="{ row }"
        ><div class="actions">
          <button class="text-button" @click="openDataset(row)">数据集</button
          ><button
            class="text-button"
            :disabled="row.status !== 4"
            @click="run(row)"
          >
            开始评测</button
          ><button
            class="text-button"
            :disabled="row.status !== 2"
            @click="showReport(row)"
          >
            查看报告
          </button>
        </div></template
      >
    </DataTable>

    <Modal v-model="createOpen" :title="dialogTitle">
      <form @submit.prevent="create">
        <label v-if="!uploadExisting" class="field"
          >数据来源<select
            v-model="form.is_custom_upload"
            @change="upload = null"
          >
            <option :value="false">知识库</option>
            <option :value="true">上传数据集</option>
          </select></label
        >
        <template v-if="!form.is_custom_upload">
          <label class="field"
            >知识库<select v-model="form.kb_id" required @change="loadDocs">
              <option value="" disabled>选择知识库</option>
              <option v-for="kb in kbs" :key="kb.id" :value="kb.id">
                {{ kb.name }}
              </option>
            </select></label
          >
          <label class="field"
            >采样方式<select v-model="form.mode">
              <option value="kb">知识库采样</option>
              <option value="doc">指定文档</option>
            </select></label
          >
          <div v-if="form.mode === 'doc'" class="check-list">
            <label
              v-for="doc in documents.filter((row) => row.status === 2)"
              :key="doc.id"
              class="check-label"
              ><input
                v-model="form.doc_ids"
                type="checkbox"
                :value="doc.id"
              />{{ doc.filename }}</label
            ><span
              v-if="!documents.some((doc) => doc.status === 2)"
              class="muted"
              >暂无已处理文档</span
            >
          </div>
          <label v-else class="field"
            >抽取文档数量<input
              v-model.number="form.num_docs"
              type="number"
              min="1"
              required
          /></label>
          <label class="field"
            >生成题数<input
              v-model.number="form.num_questions"
              type="number"
              min="1"
              max="200"
              required
          /></label>
        </template>
        <label v-else class="field"
          >数据集文件<input
            type="file"
            accept=".json,.csv,.xlsx"
            required
            @change="upload = $event.target.files?.[0] || null"
        /></label>
        <div class="form-actions">
          <button type="button" class="button" @click="createOpen = false">
            取消</button
          ><button class="button primary" :disabled="busy">
            {{
              busy
                ? "处理中…"
                : uploadExisting
                  ? "上传数据集"
                  : form.is_custom_upload
                    ? "上传并创建"
                    : "创建任务"
            }}
          </button>
        </div>
      </form>
    </Modal>

    <Modal v-model="datasetOpen" :title="`数据集 · ${task?.name || ''}`" wide>
      <div class="toolbar">
        <span class="muted">{{ items.length }} 条样本</span
        ><button class="button" @click="openDatasetUpload(task)">
          <Icon name="upload" :size="15" />上传数据集
        </button>
      </div>
      <Feedback :empty="!items.length" text="暂无评测样本" />
      <DataTable
        v-if="items.length"
        :rows="items"
        :columns="[
          { key: 'question', label: '问题', width: '39%' },
          { key: 'ground_truth', label: '参考答案', width: '41%' },
          { key: 'qa_type', label: '类型' },
          { key: 'actions', label: '' },
        ]"
      >
        <template #question="{ row }"
          ><span class="truncate">{{ row.question }}</span></template
        >
        <template #ground_truth="{ row }"
          ><span class="truncate">{{ row.ground_truth }}</span></template
        >
        <template #actions="{ row }"
          ><div class="actions">
            <button class="text-button" @click="editItem(row)">编辑</button
            ><button class="text-button danger" @click="removeItem(row)">
              删除
            </button>
          </div></template
        >
      </DataTable>
      <div class="form-actions">
        <button class="button" @click="datasetOpen = false">关闭</button
        ><button
          class="button primary"
          :disabled="task?.status !== 4"
          @click="run(task)"
        >
          开始评测
        </button>
      </div>
    </Modal>

    <Modal v-model="editorOpen" title="编辑评测样本">
      <form @submit.prevent="saveItem">
        <label class="field"
          >问题<input v-model.trim="editForm.question" required
        /></label>
        <label class="field"
          >参考答案<textarea
            v-model.trim="editForm.ground_truth"
            required
            rows="6"
          />
        </label>
        <label class="field"
          >类型<select v-model="editForm.qa_type">
            <option value="single_hop">单跳</option>
            <option value="multi_hop">多跳</option>
            <option value="error">错误样例</option>
          </select></label
        >
        <div class="form-actions">
          <button type="button" class="button" @click="editorOpen = false">
            取消</button
          ><button class="button primary" :disabled="busy">保存</button>
        </div>
      </form>
    </Modal>

    <Modal v-model="reportOpen" :title="`评测报告 · ${task?.name || ''}`" wide>
      <Markdown :content="report" />
      <div class="form-actions">
        <button class="button primary" @click="downloadReport">
          <Icon name="download" :size="16" />下载报告
        </button>
      </div>
    </Modal>
  </div>
</template>
