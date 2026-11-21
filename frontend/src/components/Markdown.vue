<script setup>
import { computed } from "vue";
import { marked } from "marked";
import DOMPurify from "dompurify";
const props = defineProps({ content: String, plainCitations: Boolean });
defineEmits(["evidence"]);
const html = computed(() =>
  DOMPurify.sanitize(marked.parse(props.content || "", { breaks: true }), {
    FORBID_TAGS: ["img", "style", "iframe", "form", "input"],
    FORBID_ATTR: ["style"],
  }).replace(/\bev-[A-Za-z0-9]{16,80}\b/g, (id, offset, text) => {
    // Evidence links are added only to text, outside HTML tags.
    return props.plainCitations || text.lastIndexOf("<", offset) > text.lastIndexOf(">", offset)
      ? id
      : `<button type="button" class="citation" data-evidence="${id}">${id}</button>`;
  }),
);
</script>
<template>
  <div
    class="markdown"
    @click="
      (event) => {
        const id = event.target.closest('[data-evidence]')?.dataset.evidence;
        if (id) $emit('evidence', id);
      }
    "
    v-html="html"
  />
</template>
