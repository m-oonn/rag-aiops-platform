<script setup>
import { computed, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import { session } from "../lib/session";
import FilePreview from "../components/FilePreview.vue";
import { request, downloadBlob } from "../lib/api";
import {
  confirmAction,
  docStatus,
  tone,
  fileSize,
  dateTime,
  fail,
  notify,
  useLoad,
} from "../lib/ui";
import PageHeader from "../components/PageHeader.vue";
import Feedback from "../components/Feedback.vue";
import DataTable from "../components/DataTable.vue";
import Modal from "../components/Modal.vue";
import Markdown from "../components/Markdown.vue";
import Icon from "../components/Icon.vue";
import InsightBreakdown from "../components/InsightBreakdown.vue";
import { breakdown } from "../lib/breakdown";
const route = useRoute(),
  id = route.params.id;
const kb = ref(null),
  documents = ref([]),
  matches = ref([]),
  searchAnswer = ref(""),
  selected = ref([]),
  search = ref(""),
  busy = ref(false),
  docFilter = ref("");
const canEdit = computed(() => kb.value?.owner_id === session.user?.id);
const searched = ref(false),
  uploadError = ref("");
const activeTab = ref("documents"),
  docModal = ref(false),
  chunkModal = ref(false),
  qaModal = ref(false),
  previewModal = ref(false),
  editQaModal = ref(false);
const focusDoc = ref(null),
  chunks = ref([]),
  preview = ref(null),
  pairs = ref([]),
  editingQA = ref(null);
const upload = ref(null),
  qaDraft = reactive({ question: "", answer: "", qa_type: "single_hop" });
const docStage = ref('');
const documentChart = computed(() => breakdown(documents.value, doc => doc.status ?? 'unknown', docStatus, tone)
  .sort((a, b) => Number(a.key) - Number(b.key)));
const visible = computed(() =>
  documents.value.filter((doc) =>
    (docStage.value === '' || (doc.status ?? 'unknown') === docStage.value) && doc.filename.toLowerCase().includes(docFilter.value.toLowerCase()),
  ),
);
const columns = [
  { key: "filename", label: "文件", width: "32%" },
  { key: "status", label: "状态" },
  { key: "chunk_count", label: "分块" },
  { key: "file_size", label: "大小" },
  { key: "created_at", label: "上传时间" },
  { key: "actions", label: "" },
];
async function load() {
  const results = await Promise.all([
    request(`/knowledge-bases/${id}`),
    request(`/knowledge-bases/${id}/documents`),
  ]);
  kb.value = results[0];
  documents.value = results[1];
}
const { loading, error, refresh } = useLoad(load);
function handleTab(value) {
  activeTab.value = value;
  if (value === "qa") {
    if (!focusDoc.value) focusDoc.value = documents.value[0] || null;
    loadPairs();
  }
}
function openQa(row) {
  focusDoc.value = row;
  activeTab.value = "qa";
  loadPairs();
}
async function loadPairs() {
  if (!focusDoc.value) {
    pairs.value = [];
    return;
  }
  try {
    pairs.value = await request(
      `/knowledge-bases/documents/${focusDoc.value.id}/qa-pairs`,
    );
  } catch (e) {
    fail(e);
  }
}
async function saveUpload() {
  if (!upload.value) return;
  uploadError.value = "";
  if (upload.value.size > 50 * 1024 * 1024) {
    uploadError.value = "文件不能超过 50 MB";
    return;
  }
  if (!/\.(pdf|docx?|xlsx?|csv|pptx?|md|html?|txt)$/i.test(upload.value.name)) {
    uploadError.value = "请选择支持的文档格式";
    return;
  }
  busy.value = true;
  try {
    const data = new FormData();
    data.append("file", upload.value);
    await request(`/knowledge-bases/${id}/upload`, {
      method: "POST",
      body: data,
    });
    upload.value = null;
    docModal.value = false;
    await refresh();
    notify("文档已提交处理");
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}
async function retry(row) {
  try {
    await request(`/knowledge-bases/documents/${row.id}/retry`, {
      method: "POST",
    });
    notify("已重新提交");
    await refresh();
  } catch (e) {
    fail(e);
  }
}
async function batchRetry() {
  try {
    await request("/knowledge-bases/documents/batch-retry", {
      method: "POST",
      body: selected.value,
    });
    selected.value = [];
    notify("已重新提交");
    await refresh();
  } catch (e) {
    fail(e);
  }
}
async function removeDocs(ids = [focusDoc.value?.id].filter(Boolean)) {
  if (
    !ids.length ||
    !(await confirmAction(
      "删除文档",
      `将删除 ${ids.length} 个文档及其关联内容。`,
      "删除",
      true,
    ))
  )
    return;
  try {
    await request("/knowledge-bases/documents/batch-delete", {
      method: "DELETE",
      body: ids,
    });
    selected.value = [];
    await refresh();
    notify("文档已删除");
  } catch (e) {
    fail(e);
  }
}
async function showChunks(row) {
  focusDoc.value = row;
  try {
    const data = await request(`/knowledge-bases/documents/${row.id}/chunks`, {
      query: { limit: 100 },
    });
    chunks.value = data.chunks || data || [];
    chunkModal.value = true;
  } catch (e) {
    fail(e);
  }
}
async function showPreview(row) {
  focusDoc.value = row;
  try {
    preview.value = await request(
      `/knowledge-bases/documents/${row.id}/preview`,
      { blob: true },
    );
    previewModal.value = true;
  } catch (e) {
    fail(e);
  }
}
async function generateQA(row) {
  if (
    !(await confirmAction(
      "生成问答对",
      `根据“${row.filename}”生成 5 组问答？`,
      "开始生成",
    ))
  )
    return;
  try {
    await request(`/knowledge-bases/documents/${row.id}/generate-qa`, {
      method: "POST",
      query: { num_pairs: 5 },
    });
    focusDoc.value = row;
    await loadPairs();
    activeTab.value = "qa";
    qaModal.value = true;
  } catch (e) {
    fail(e);
  }
}
function editPair(row = null) {
  editingQA.value = row;
  Object.assign(qaDraft, {
    question: row?.question || "",
    answer: row?.answer || "",
    qa_type: row?.qa_type || "single_hop",
  });
  editQaModal.value = true;
}
async function savePair() {
  busy.value = true;
  try {
    const path = editingQA.value
      ? `/knowledge-bases/qa-pairs/${editingQA.value.id}`
      : `/knowledge-bases/documents/${focusDoc.value.id}/qa-pairs`;
    await request(path, {
      method: editingQA.value ? "PUT" : "POST",
      body: { ...qaDraft },
    });
    editQaModal.value = false;
    await loadPairs();
    notify("问答对已保存");
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}
async function deletePair(row) {
  if (!(await confirmAction("删除问答对", "此操作无法撤销。", "删除", true)))
    return;
  try {
    await request(`/knowledge-bases/qa-pairs/${row.id}`, { method: "DELETE" });
    await loadPairs();
    notify("问答对已删除");
  } catch (e) {
    fail(e);
  }
}
async function exportPairs() {
  try {
    downloadBlob(
      await request(
        `/knowledge-bases/documents/${focusDoc.value.id}/qa-pairs/download`,
        { blob: true },
      ),
      `${focusDoc.value.filename}-qa.xlsx`,
    );
  } catch (e) {
    fail(e);
  }
}
async function searchKnowledge() {
  if (!search.value.trim() || !kb.value) return;
  busy.value = true;
  matches.value = [];
  searchAnswer.value = "";
  searched.value = false;
  try {
    if (kb.value.chunking_config?.retrieval_mode === "bm25") {
      const result = await request(`/knowledge-bases/${id}/search`, {
        method: "POST",
        body: { query: search.value.trim(), top_k: 5 },
      });
      matches.value = result.results || [];
    } else {
      const result = await request("/chat/", {
        method: "POST",
        body: { query: search.value.trim(), kb_id: Number(id), top_k: 5 },
      });
      matches.value = result.source_documents || [];
      searchAnswer.value = result.answer || "";
    }
    searched.value = true;
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}
async function reprocess(row) {
  if (
    !(await confirmAction(
      "重新处理文档",
      `将按“${kb.value.name}”的当前设置重新处理该文档？`,
      "重新处理",
    ))
  )
    return;
  try {
    await request(`/knowledge-bases/documents/${row.id}/reprocess`, {
      method: "POST",
      body: kb.value.chunking_config || {},
    });
    await refresh();
    notify("已提交重新处理");
  } catch (e) {
    fail(e);
  }
}
</script>
<template>
  <div class="page">
    <PageHeader :title="kb?.name || '文档与检索'" back="/knowledge-bases"
      ><button class="button" :disabled="loading" @click="refresh()">
        <Icon name="refresh" :size="16" />刷新</button
      ><button v-if="canEdit" class="button primary" @click="docModal = true">
        <Icon name="upload" :size="17" />上传文档
      </button></PageHeader
    ><Feedback :loading="loading" :error="error" @retry="refresh()" /><template
      v-if="!loading && kb"
      ><div class="summary-line">
        <span>{{ kb.is_public ? "公开知识库" : "个人知识库" }}</span
        ><span>{{ documents.length }} 个文档</span
        ><span
          >{{
            documents.reduce((sum, doc) => sum + (doc.chunk_count || 0), 0)
          }}
          个分块</span
        ><span>{{ dateTime(kb.created_at) }} 创建</span>
      </div>
      <nav class="tabs" aria-label="知识库内容">
        <button
          :class="{ active: activeTab === 'documents' }"
          @click="handleTab('documents')"
        >
          文档 <span class="count">{{ documents.length }}</span></button
        ><button
          :class="{ active: activeTab === 'qa' }"
          @click="handleTab('qa')"
        >
          问答对 <span class="count">{{ pairs.length }}</span></button
        ><button
          :class="{ active: activeTab === 'search' }"
          @click="handleTab('search')"
        >
          知识检索</button
        ><button
          :class="{ active: activeTab === 'settings' }"
          @click="handleTab('settings')"
        >
          设置
        </button>
      </nav>
      <template v-if="activeTab === 'documents'">
        <InsightBreakdown v-model="docStage" :items="documentChart" title="文档入库阶段" icon="workflow"
          description="点击阶段查看对应文档及分块结果。" variant="stages" unit="份" @update:model-value="selected = []" />
        <div class="toolbar">
          <label class="search-input"
            ><Icon name="search" /><input
              v-model="docFilter"
              type="search"
              placeholder="搜索文档"
              aria-label="搜索文档"
          /></label>
          <div class="actions">
            <button v-if="selected.length" class="button" @click="batchRetry">
              重试 {{ selected.length }} 项</button
            ><button
              v-if="selected.length"
              class="button danger"
              @click="removeDocs(selected)"
            >
              删除 {{ selected.length }} 项</button
            ><span class="muted">{{ visible.length }} 个文件</span>
          </div>
        </div>
        <Feedback :empty="!visible.length" :loading="false"
          ><span>没有匹配的文档</span></Feedback
        ><DataTable
          v-if="visible.length"
          v-model="selected"
          :rows="visible"
          :columns="columns"
          :selectable="canEdit"
          ><template #filename="{ row }"
            ><div class="cell-title">
              <Icon name="file" /><button
                class="text-button"
                @click="showPreview(row)"
              >
                {{ row.filename }}
              </button>
            </div></template
          ><template #status="{ row }"
            ><span :class="['status', tone(row.status)]">{{
              docStatus(row.status)
            }}</span></template
          ><template #chunk_count="{ row }">{{ row.chunk_count ?? 0 }}</template
          ><template #file_size="{ row }">{{
            fileSize(row.file_size)
          }}</template
          ><template #created_at="{ row }">{{
            dateTime(row.created_at)
          }}</template
          ><template #actions="{ row }"
            ><div class="actions">
              <button
                class="text-button"
                :disabled="row.status !== 2"
                @click="showChunks(row)"
              >
                分块</button
              ><button
                class="text-button"
                :disabled="row.status !== 2"
                @click="openQa(row)"
              >
                问答对</button
              ><button
                class="text-button"
                :disabled="row.status !== 2"
                v-if="canEdit"
                @click="generateQA(row)"
              >
                生成问答</button
              ><button
                v-if="canEdit && row.status === 3"
                class="text-button"
                @click="retry(row)"
              >
                重试</button
              ><button
                class="text-button"
                :disabled="row.status !== 2"
                v-if="canEdit"
                @click="reprocess(row)"
              >
                重新处理</button
              ><button
                class="text-button danger"
                v-if="canEdit"
                @click="removeDocs([row.id])"
              >
                删除
              </button>
            </div></template
          ></DataTable
        ></template
      >
      <section v-if="activeTab === 'qa'">
        <div class="toolbar">
          <span class="muted">{{
            focusDoc?.filename || "选择文档查看问答对"
          }}</span>
          <div class="actions">
            <select
              v-if="documents.length > 1"
              v-model="focusDoc"
              class="filter-select"
              aria-label="选择文档"
              @change="loadPairs"
            >
              <option v-for="doc in documents" :key="doc.id" :value="doc">
                {{ doc.filename }}
              </option></select
            ><button
              class="button"
              :disabled="!focusDoc"
              v-if="canEdit"
              @click="editPair()"
            >
              <Icon name="plus" :size="16" />新增问答对</button
            ><button class="button" :disabled="!focusDoc" @click="exportPairs">
              导出
            </button>
          </div>
        </div>
        <Feedback
          :empty="!pairs.length"
          :text="focusDoc ? '暂无问答对' : '此知识库暂无可用文档'"
        /><DataTable
          v-if="pairs.length"
          :rows="pairs"
          :columns="[
            { key: 'question', label: '问题', width: '40%' },
            { key: 'answer', label: '答案', width: '40%' },
            { key: 'qa_type', label: '类型' },
            { key: 'actions', label: '' },
          ]"
          ><template #question="{ row }"
            ><span class="truncate">{{ row.question }}</span></template
          ><template #answer="{ row }"
            ><span class="truncate">{{ row.answer }}</span></template
          ><template #actions="{ row }"
            ><div class="actions">
              <button class="text-button" v-if="canEdit" @click="editPair(row)">
                编辑</button
              ><button
                class="text-button danger"
                v-if="canEdit"
                @click="deletePair(row)"
              >
                删除
              </button>
            </div></template
          ></DataTable
        >
      </section>
      <section v-if="activeTab === 'search'">
        <form class="probe-search" @submit.prevent="searchKnowledge">
          <input
            v-model.trim="search"
            :placeholder="
              kb.chunking_config?.retrieval_mode === 'bm25'
                ? '输入关键词'
                : '输入需要查询的问题'
            "
            aria-label="知识检索关键词"
            required
            maxlength="1000"
          /><button class="button primary" :disabled="busy">
            <Icon name="search" :size="16" />{{
              kb.chunking_config?.retrieval_mode === "bm25" ? "检索" : "查询"
            }}
          </button>
        </form>
        <Feedback v-if="busy" :loading="true" /><Feedback
          v-else
          :empty="searched && !matches.length && !searchAnswer"
          text="未找到相关内容"
        /><Markdown v-if="searchAnswer" :content="searchAnswer" />
        <article
          v-for="(match, i) in matches"
          :key="match.chunk_id || i"
          class="detail-line"
        >
          <div class="actions">
            <span class="tag">{{
              match.metadata?.filename ||
              match.filename ||
              match.source ||
              "知识片段"
            }}</span
            ><span class="muted">{{
              Number(match.score || 0).toFixed(3)
            }}</span>
          </div>
          <p>{{ match.content || match.text }}</p>
        </article>
      </section>
      <section v-if="activeTab === 'settings'">
        <dl class="detail-facts">
          <dt>分块方式</dt>
          <dd>{{ kb.chunking_config?.method || "默认" }}</dd>
          <dt>分块长度</dt>
          <dd>{{ kb.chunking_config?.chunk_size || "默认" }}</dd>
          <dt>重叠长度</dt>
          <dd>{{ kb.chunking_config?.chunk_overlap ?? "默认" }}</dd>
          <dt>检索模式</dt>
          <dd>
            {{
              kb.chunking_config?.retrieval_mode === "bm25"
                ? "关键词检索"
                : "混合检索"
            }}
          </dd>
          <dt>访问权限</dt>
          <dd>{{ kb.is_public ? "公开" : "仅自己" }}</dd>
        </dl>
        <RouterLink
          v-if="canEdit"
          class="button"
          :to="{ path: '/knowledge-bases', query: { edit: String(id) } }"
          >编辑知识库</RouterLink
        >
      </section></template
    ><Modal v-model="docModal" title="上传文档"
      ><div class="upload-zone">
        <Icon name="upload" :size="28" /><strong>{{
          upload?.name || "选择文档文件"
        }}</strong
        ><input
          type="file"
          accept=".pdf,.docx,.doc,.txt,.md,.html,.htm,.csv,.xlsx,.xls,.ppt,.pptx"
          aria-label="选择文档"
          @change="upload = $event.target.files?.[0] || null"
        />
      </div>
      <p v-if="uploadError" class="field-error" role="alert">
        {{ uploadError }}
      </p>
      <div class="form-actions">
        <button class="button" @click="docModal = false">取消</button
        ><button
          class="button primary"
          :disabled="busy || !upload"
          @click="saveUpload"
        >
          {{ busy ? "上传中…" : "开始处理" }}
        </button>
      </div></Modal
    ><Modal v-model="chunkModal" :title="focusDoc?.filename || '文档分块'" wide
      ><div v-if="!chunks.length" class="empty-state compact">尚无分块</div>
      <article
        v-for="chunk in chunks"
        :key="chunk.id || chunk.chunk_uid"
        class="detail-line"
      >
        <div class="actions">
          <span class="tag">{{
            chunk.page_num ? `第 ${chunk.page_num} 页` : "文本片段"
          }}</span
          ><span class="muted">{{ chunk.chunk_uid }}</span>
        </div>
        <p>{{ chunk.content }}</p>
      </article></Modal
    ><Modal v-model="qaModal" title="问答对"
      ><Feedback :empty="!pairs.length" text="暂无问答对" />
      <div v-for="pair in pairs" :key="pair.id" class="detail-line">
        <strong>Q&nbsp; {{ pair.question }}</strong>
        <p>A&nbsp; {{ pair.answer }}</p>
      </div>
      <div class="form-actions">
        <button class="button" @click="qaModal = false">关闭</button
        ><button class="button primary" v-if="canEdit" @click="editPair()">
          新增问答对
        </button>
      </div></Modal
    ><Modal
      v-model="editQaModal"
      :title="editingQA ? '编辑问答对' : '新增问答对'"
      ><form @submit.prevent="savePair">
        <label class="field"
          >问题<input
            v-model.trim="qaDraft.question"
            required
            maxlength="4000" /></label
        ><label class="field"
          >答案<textarea
            v-model.trim="qaDraft.answer"
            rows="7"
            required
            maxlength="12000"
          /></label
        ><label class="field"
          >类型<select v-model="qaDraft.qa_type">
            <option value="single_hop">单跳</option>
            <option value="multi_hop">多跳</option>
            <option value="error">错误示例</option>
          </select></label
        >
        <div class="form-actions">
          <button type="button" class="button" @click="editQaModal = false">
            取消</button
          ><button class="button primary" :disabled="busy">保存</button>
        </div>
      </form></Modal
    ><Modal
      v-model="previewModal"
      :title="focusDoc?.filename || '文档预览'"
      wide
      ><FilePreview :blob="preview"
    /></Modal>
  </div>
</template>
