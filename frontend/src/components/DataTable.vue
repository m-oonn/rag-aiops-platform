<script setup>
import { ref, computed, watch } from "vue";
const props = defineProps({
  rows: { type: Array, default: () => [] },
  columns: Array,
  rowKey: { type: String, default: "id" },
  selectable: Boolean,
  modelValue: { type: Array, default: () => [] },
  pageSize: { type: Number, default: 12 },
  paginationLabel: { type: String, default: "" },
});
const emit = defineEmits(["update:modelValue"]);
const page = ref(1);
const pages = computed(() =>
  Math.max(1, Math.ceil(props.rows.length / props.pageSize)),
);
const visible = computed(() =>
  props.rows.slice(
    (page.value - 1) * props.pageSize,
    page.value * props.pageSize,
  ),
);
watch(
  () => props.rows,
  () => {
    page.value = Math.min(page.value, pages.value);
  },
);
const all = computed(
  () =>
    visible.value.length > 0 &&
    visible.value.every((row) => props.modelValue.includes(row[props.rowKey])),
);
function select(id, checked) {
  emit(
    "update:modelValue",
    checked
      ? [...new Set([...props.modelValue, id])]
      : props.modelValue.filter((value) => value !== id),
  );
}
function selectPage(checked) {
  const ids = visible.value.map((row) => row[props.rowKey]);
  emit(
    "update:modelValue",
    checked
      ? [...new Set([...props.modelValue, ...ids])]
      : props.modelValue.filter((id) => !ids.includes(id)),
  );
}
</script>
<template>
  <div class="table-scroll" tabindex="0" aria-label="数据表格">
    <table>
      <thead>
        <tr>
          <th v-if="selectable" class="check-column">
            <input
              type="checkbox"
              aria-label="选择本页全部"
              :checked="all"
              @change="selectPage($event.target.checked)"
            />
          </th>
          <th
            v-for="col in columns"
            :key="col.key"
            :style="{ width: col.width }"
            :class="col.key === 'actions' ? 'align-right' : ''"
            scope="col"
          >
            {{ col.label }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in visible" :key="row[rowKey]">
          <td v-if="selectable" class="check-column">
            <input
              type="checkbox"
              :aria-label="`选择 ${row.name || row.filename || row.question || row[rowKey]}`"
              :checked="modelValue.includes(row[rowKey])"
              @change="select(row[rowKey], $event.target.checked)"
            />
          </td>
          <td
            v-for="col in columns"
            :key="col.key"
            :class="col.key === 'actions' ? 'align-right' : ''"
          >
            <slot :name="col.key" :row="row">{{ row[col.key] ?? "—" }}</slot>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <footer v-if="rows.length > pageSize" class="pagination">
    <span>{{ paginationLabel }}共 {{ rows.length }} 项</span>
    <div class="actions">
      <button
        class="button small"
        :disabled="page === 1"
        aria-label="上一页"
        @click="page--"
      >
        ←</button
      ><span>{{ page }} / {{ pages }}</span
      ><button
        class="button small"
        :disabled="page === pages"
        aria-label="下一页"
        @click="page++"
      >
        →
      </button>
    </div>
  </footer>
</template>
