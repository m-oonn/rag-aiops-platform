<script setup>
import { computed, ref } from "vue";
import { request, downloadBlob } from "../lib/api";
import {
  confirmAction,
  fail,
  notify,
  useLoad,
  fileSize,
  dateTime,
} from "../lib/ui";
import PageHeader from "../components/PageHeader.vue";
import Feedback from "../components/Feedback.vue";
import DataTable from "../components/DataTable.vue";
import Modal from "../components/Modal.vue";
import FilePreview from "../components/FilePreview.vue";
import Icon from "../components/Icon.vue";
const files = ref([]),
  selected = ref([]),
  search = ref(""),
  prefix = ref(""),
  upload = ref(null),
  busy = ref(false),
  previewing = ref(null),
  previewBlob = ref(null);
const visible = computed(() =>
  files.value.filter((file) =>
    `${file.object_name || file.name || ""}`
      .toLowerCase()
      .includes(search.value.toLowerCase()),
  ),
);
const { loading, error, refresh } = useLoad(async () => {
  const result = await request("/storage/files", {
    query: {
      prefix: prefix.value,
      search_query: search.value,
      sort_by: "last_modified",
      order: "desc",
    },
  });
  files.value = result.files || [];
});
async function saveUpload() {
  if (!upload.value) return;
  busy.value = true;
  try {
    const data = new FormData();
    data.append("file", upload.value);
    await request("/storage/upload", {
      method: "POST",
      body: data,
      query: { prefix: prefix.value },
    });
    upload.value = null;
    await refresh();
    notify("文件已上传");
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}
const objectName = (file) => file.object_name || file.name;
async function download(file) {
  try {
    const blob = await request(
      `/storage/download/${encodeURIComponent(objectName(file))}`,
      { blob: true },
    );
    downloadBlob(blob, objectName(file).split("/").at(-1));
  } catch (e) {
    fail(e);
  }
}
async function preview(file) {
  try {
    previewBlob.value = null;
    const blob = await request(
      `/storage/preview/${encodeURIComponent(objectName(file))}`,
      { blob: true },
    );
    previewBlob.value = blob;
    previewing.value = file;
  } catch (e) {
    fail(e);
  }
}
async function removeSelected() {
  if (
    !selected.value.length ||
    !(await confirmAction(
      "删除文件",
      `永久删除 ${selected.value.length} 个文件？`,
      "永久删除",
      true,
    ))
  )
    return;
  try {
    await request("/storage/batch-delete", {
      method: "POST",
      body: { object_names: selected.value },
    });
    selected.value = [];
    await refresh();
    notify("文件已删除");
  } catch (e) {
    fail(e);
  }
}
</script>
<template>
  <div class="page">
    <PageHeader title="文件管理"
      ><button class="button" :disabled="loading" @click="refresh()">
        <Icon name="refresh" :size="16" />刷新
      </button></PageHeader
    >
    <form class="upload-zone" @submit.prevent="saveUpload">
      <div class="file-picker">
        <Icon name="upload" :size="24" /><label class="button"
          >选择文件<input
            class="sr-only"
            type="file"
            aria-label="选择上传文件"
            @change="upload = $event.target.files?.[0] || null" /></label
        ><span class="muted">{{ upload?.name || "选择文件后上传" }}</span
        ><input
          v-model.trim="prefix"
          class="filter-select"
          placeholder="文件夹路径"
          aria-label="保存到文件夹"
        />
      </div>
      <button class="button primary" :disabled="busy || !upload">
        <span v-if="busy" class="spinner" />上传
      </button>
    </form>
    <div class="toolbar">
      <label class="search-input"
        ><Icon name="search" /><input
          v-model="search"
          type="search"
          placeholder="搜索文件名"
          aria-label="搜索文件"
          @change="refresh()" /></label
      ><button
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
      text="暂无文件"
      @retry="refresh()"
    /><DataTable
      v-if="visible.length"
      v-model="selected"
      :rows="visible"
      selectable
      :row-key="'object_name'"
      :columns="[
        { key: 'object_name', label: '文件名', width: '44%' },
        { key: 'size', label: '大小' },
        { key: 'last_modified', label: '修改时间' },
        { key: 'actions', label: '' },
      ]"
      ><template #object_name="{ row }"
        ><div class="cell-title">
          <Icon name="file" /><span>{{ objectName(row) }}</span>
        </div></template
      ><template #size="{ row }">{{ fileSize(row.size) }}</template
      ><template #last_modified="{ row }">{{
        dateTime(row.last_modified)
      }}</template
      ><template #actions="{ row }"
        ><div class="actions">
          <button class="text-button" @click="preview(row)">预览</button
          ><button class="text-button" @click="download(row)">下载</button>
        </div></template
      ></DataTable
    ><Modal
      :model-value="Boolean(previewing)"
      :title="previewing?.object_name || '文件预览'"
      wide
      @update:model-value="!$event && (previewing = null)"
      ><FilePreview :blob="previewBlob"
    /></Modal>
  </div>
</template>
